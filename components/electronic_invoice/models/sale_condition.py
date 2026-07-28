from odoo import models, fields


class SaleConditions(models.Model):
    _name = "sale.conditions"
    _description = 'Sale Conditions'

    active = fields.Boolean(
        default=True
    )
    code = fields.Char()
    sequence = fields.Char()
    name = fields.Char()
    notes = fields.Text()
