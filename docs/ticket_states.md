# Ticket States #

## The states ##
There are 7 states that a purchase can be in:

* **Reserved** -- The purchase is in a basket, no payment has been selected (the user may not have an account at this point).
* **Payment-pending** -- The payment is being processed
* **Expired** -- Either the reservation or the payment has expired
* **Cancelled** -- The purchase was cancelled from the basket
* **Paid** -- The purchase has been paid for
* **Receipt-emailed** -- The purchase has been sent out
* **Refunded** -- The purchase has been refunded

## Allowed Transitions ##

Transitions between states are limited to:

* reserved -> payment-pending, expired, cancelled
* payment-pending -> expired, paid
* expired -> 
* cancelled -> 
* paid -> receipt-emailed, refunded
* receipt-emailed -> paid, refunded
* refunded -> 

Some states have no allowed transitions away from them (*expired*, *cancelled* and *refunded*).

## Bought ##

Purchases are considered to have been bought when they are in either the *paid* or *receipt-emailed* states (e.g. a ticket is valid for entrance when it's in one of these).

## Non-blocking states ##

The number of purchases of a particular type a user may make is limited (normally to 10). Some states don't count towards this limit, these are *expired*, *refunded* and *cancelled*. E.g. a user reserves 10 standard tickets then doesn't select a payment method so they expire, when they come back a day later they can reserve another 10 tickets. Conversely if they finish paying for those 10 tickets they can buy no more (unless they refund some of them).
