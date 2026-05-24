"""Message queue abstraction.

The rest of the app depends ONLY on the `MessageQueue` interface (base.py), never
on a concrete backend. To scale later (AWS SQS, RabbitMQ, Kafka), add a new
implementation and register it in factory.py — no handler or business-logic code
changes.
"""
