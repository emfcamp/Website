from locust import HttpUser, task, between
from locust.exception import StopUser

import lxml.html


"""
Run this with e.g.:

    run locust -f tests/locust/tickets.py --headless -u 1000 -r 100 --host https://www.emfcamp-test.org

"""


class CheckTicketsUser(HttpUser):
    wait_time = between(1, 2)

    @task
    def index(self):
        self.client.get("/")

    @task
    def tickets(self):
        self.client.get("/tickets")


class ReserveTicketsUser(HttpUser):
    wait_time = between(0, 1)

    """
    These numbers are based on the first round of 2018.
    Supporter tickets and campervans are the same as full tickets and parking
    from a performance perspective, and people don't tend to mix them.

    select products, count(*), sum(count(*)) over (order by count(*)) total from (
     select purchaser_id, string_agg(product_name, ',' order by product_name) products from (
      select c.purchaser_id, replace(replace(replace(o.name, 'campervan', 'parking'), 'full-sg', 'full'), 'full-s', 'full') product_name
      from purchase c, product o
      where
       c.state in ('paid', 'payment-pending')
       and o.id = c.product_id
     ) x
     group by purchaser_id
    ) x
    group by products order by count(*) desc;
    """

    @task(60)
    def reserve_full(self):
        self.reserve_tickets({"Full Camp Ticket": 1})

    @task(25)
    def reserve_full_parking(self):
        self.reserve_tickets({"Full Camp Ticket": 1, "Parking Ticket": 1})

    @task(20)
    def reserve_2_full(self):
        self.reserve_tickets({"Full Camp Ticket": 2})

    @task(20)
    def reserve_2_full_parking(self):
        self.reserve_tickets({"Full Camp Ticket": 2, "Parking Ticket": 1})

    @task(10)
    def reserve_family(self):
        self.reserve_tickets(
            {"Full Camp Ticket": 2, "Under-18": 2, "Parking Ticket": 1}
        )

    def reserve_tickets(self, tickets):
        # Make sure we have a clean session
        self.client.cookies.clear()

        self.client.get("/")

        resp = self.client.get("/tickets")

        html = lxml.html.fromstring(resp.content)
        form = html.get_element_by_id("choose_tickets")
        amounts = {
            i.label.text_content(): i.name
            for i in form.inputs
            if i.name.endswith("-amount")
        }

        data = dict(**form.fields)
        for display_name, count in tickets.items():
            data[amounts[display_name]] = count

        self.client.post("/tickets", data)

        raise StopUser()
