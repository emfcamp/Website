from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('../templates'))

def test(template, count = 2):
  template = env.get_template(template)
  basket = { "cost" : 42.00, "count" : count, "reference" : "abc123-45" }
  output=template.render(basket=basket, user = {"name" : "J R Hartley"})
  print output


if __name__ == "__main__":
  for t in ("tickets-purchased-email.txt", "payment-received-email.txt"):
    test(t)
    print
    print "*" * 42
    print

  # and the singular versions
  for t in ("tickets-purchased-email.txt", "payment-received-email.txt"):
    test(t, 1)
    print
    print "*" * 42
    print

  
  