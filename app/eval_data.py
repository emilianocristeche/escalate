"""Small labeled evaluation set for the classifier benchmark.

Synthetic tickets with gold (severity, category) labels. Deliberately mixes
easy keyword-matchable tickets with hard ones the rules are expected to miss:
Spanish text, no-keyword phrasing, and sarcasm. This is what makes the
rules-vs-LLM benchmark meaningful — a set the rules ace 100% proves nothing.
"""

# (subject, body, gold_severity, gold_category)
LABELED = [
    # --- easy: rules should nail these ---
    ("Total outage, all customers affected", "nothing works", "P1", "general"),
    ("Payments API returning 500", "every charge fails", "P2", "billing"),
    ("How do I export my invoices?", "", "P4", "billing"),
    ("eSIM has no signal", "provisioned but dead", "P2", "connectivity"),
    ("Refund not processed on invoice", "", "P3", "billing"),
    ("Webhook endpoint timeout", "integration 500", "P2", "api"),
    ("Locked out of my account", "2fa reset", "P3", "account"),
    ("Feature request: dark mode", "", "P4", "general"),
    ("Network connection drops on roaming", "", "P3", "connectivity"),
    ("Login page shows a 500 error", "blocked at sign in", "P2", "account"),
    ("Cannot pay, card reader outage", "", "P1", "billing"),
    ("Rate limit token rejected on api", "", "P2", "api"),
    ("Question about my subscription price", "", "P4", "billing"),
    ("Password reset email never arrives", "", "P3", "account"),
    ("SIM roaming charges look wrong", "", "P3", "connectivity"),

    # --- hard: no keyword / phrasing the rules will likely miss ---
    ("Everything is on fire and money is not moving", "whole platform stuck", "P1", "billing"),
    ("The app just spins forever when I click save", "", "P2", "general"),
    ("Your service ate my money and gave nothing back", "great job", "P2", "billing"),
    ("Nobody can get in this morning", "team blocked at the door", "P1", "account"),
    ("It stopped doing the thing it used to do", "", "P2", "general"),

    # --- hard: Spanish (rules are English-only) ---
    ("No puedo cobrar, el lector esta caido", "", "P1", "billing"),
    ("La tarjeta SIM no tiene senal", "", "P2", "connectivity"),
    ("Como exporto mis facturas?", "", "P4", "billing"),
    ("No puedo iniciar sesion, contrasena rechazada", "", "P3", "account"),
    ("El webhook devuelve error 500 intermitente", "", "P2", "api"),

    # --- medium: mixed signals ---
    ("Billing question but also everything is down", "", "P1", "billing"),
    ("Slow API responses since the update", "not an outage yet", "P3", "api"),
    ("Reader works but receipts do not print", "", "P3", "billing"),
    ("Account fine, just curious how roaming is charged", "", "P4", "connectivity"),
    ("Urgent: production integration failing for all merchants", "", "P1", "api"),
]
