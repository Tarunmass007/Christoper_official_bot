"""Credit deduction; uses BOT.db.store (MongoDB or JSON)."""

from BOT.db import store

def deduct_credit(user_id):
    return store.deduct_credit(str(user_id))

def has_credits(user_id):
    return store.has_credits(str(user_id))

def deduct_credit_bulk(user_id, amount):
    return store.deduct_credit_bulk(str(user_id), amount)
