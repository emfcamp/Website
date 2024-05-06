from flask import Response, Blueprint
from prometheus_client import (
    PlatformCollector,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
)
from prometheus_client.core import GaugeMetricFamily, Histogram, Counter
from prometheus_client.multiprocess import MultiProcessCollector
from sqlalchemy import cast, String, case
from datetime import datetime

from models import count_groups
from models.email import EmailJobRecipient
from models.payment import Payment
from models.product import Product, ProductView, Voucher, VOUCHER_GRACE_PERIOD
from models.purchase import Purchase, AdmissionTicket
from models.cfp import Proposal

metrics = Blueprint("metric", __name__)

request_duration = Histogram("emf_request_duration_seconds", "Request duration", ["endpoint", "method"])
request_total = Counter("emf_request_total", "Total request count", ["endpoint", "method", "http_status"])


def gauge_groups(gauge, query, *entities):
    for count, *key in count_groups(query, *entities):
        gauge.add_metric(key, count)


class ExternalMetrics:
    def __init__(self, registry=None):
        if registry is not None:
            registry.register(self)

    def collect(self):
        # Strictly, we should include all possible combinations, with 0

        emf_purchases = GaugeMetricFamily(
            "emf_purchases", "Tickets purchased", labels=["product", "state", "type"]
        )
        emf_payments = GaugeMetricFamily("emf_payments", "Payments received", labels=["provider", "state"])
        emf_attendees = GaugeMetricFamily("emf_attendees", "Attendees", labels=["checked_in", "badged_up"])
        emf_proposals = GaugeMetricFamily("emf_proposals", "CfP Submissions", labels=["type", "state"])
        emf_email_jobs = GaugeMetricFamily("emf_emails", "Email recipients", labels=["sent"])
        emf_vouchers = GaugeMetricFamily("emf_vouchers", "Vouchers", labels=["product_view", "state"])

        gauge_groups(
            emf_purchases,
            Purchase.query.join(Product),
            Product.name,
            Purchase.state,
            Purchase.type,
        )
        gauge_groups(emf_payments, Payment.query, Payment.provider, Payment.state)
        gauge_groups(
            emf_attendees,
            AdmissionTicket.query.filter(AdmissionTicket.is_paid_for),
            cast(AdmissionTicket.checked_in, String),
            cast(AdmissionTicket.badge_issued, String),
        )
        gauge_groups(emf_proposals, Proposal.query, Proposal.type, Proposal.state)
        gauge_groups(
            emf_email_jobs,
            EmailJobRecipient.query,
            cast(EmailJobRecipient.sent, String),
        )

        gauge_groups(
            emf_vouchers,
            Voucher.query.join(ProductView),
            ProductView.name,
            case(
                (Voucher.is_used == True, "used"),  # noqa: E712
                (
                    (Voucher.expiry != None)  # noqa: E711
                    & (Voucher.expiry < datetime.utcnow() - VOUCHER_GRACE_PERIOD),
                    "expired",
                ),  # noqa: E712
                else_="active",
            ),
        )

        return [
            emf_purchases,
            emf_payments,
            emf_attendees,
            emf_proposals,
            emf_email_jobs,
            emf_vouchers,
        ]


@metrics.route("/metrics")
def collect_metrics():
    registry = CollectorRegistry()
    MultiProcessCollector(registry)
    PlatformCollector(registry)
    ExternalMetrics(registry)

    data = generate_latest(registry)

    return Response(data, mimetype=CONTENT_TYPE_LATEST)
