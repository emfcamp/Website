from flask import (
    Response, Blueprint,
)
from prometheus_client import (
    PlatformCollector, CollectorRegistry,
    generate_latest, CONTENT_TYPE_LATEST,
)
from prometheus_client.core import (
    Gauge, GaugeMetricFamily, Histogram, Counter,
)
from prometheus_client.multiprocess import MultiProcessCollector
from sqlalchemy import cast, String

from models import count_groups
from models.payment import Payment
from models.product import Product
from models.purchase import Purchase, AdmissionTicket

metrics = Blueprint('metric', __name__)

external_scrape = Histogram('external_scrape_duration_seconds', "Time to fetch out-of-process metrics")
request_duration = Histogram('emf_request_duration_seconds', "Request duration", ['endpoint', 'method'])
request_count = Counter('emf_request_count', "Request Count", ['endpoint', 'method', 'http_status'])

def gauge_groups(gauge, query, *entities):
    for count, *key in count_groups(query, *entities):
        gauge.add_metric(key, count)

# Custom collectors don't work
class ExternalMetrics:
    @external_scrape.time()
    def collect(self):
        # Strictly, we should include all possible combinations, with 0

        emf_purchases = GaugeMetricFamily('emf_purchases', "Purchases", labels=['product', 'state'])
        emf_payments = GaugeMetricFamily('emf_payments', "Payments", labels=['provider', 'state'])
        emf_attendees = GaugeMetricFamily('emf_attendees', "Attendees", labels=['checked_in', 'badged_up'])

        gauge_groups(emf_purchases, Purchase.query.join(Product),
                     Product.name, Purchase.state)
        gauge_groups(emf_payments, Payment.query,
                     Payment.provider, Payment.state)
        gauge_groups(emf_attendees, AdmissionTicket.query,
                     cast(AdmissionTicket.checked_in, String), cast(AdmissionTicket.badge_issued, String))

        return [
            emf_purchases,
            emf_payments,
            emf_attendees,
        ]


@metrics.route('/metrics')
def collect_metrics():
    registry = CollectorRegistry()
    registry.register(MultiProcessCollector(None))
    registry.register(PlatformCollector(None))
    registry.register(ExternalMetrics())

    data = generate_latest(registry)

    return Response(data, mimetype=CONTENT_TYPE_LATEST)

