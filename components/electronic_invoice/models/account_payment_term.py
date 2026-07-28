from odoo import models, fields


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"
    _description = 'Account Payment Term'

    # ==============================================================================================
    #                                          SALE CONDITION
    # ==============================================================================================

    sale_conditions_id = fields.Many2one(
        comodel_name="sale.conditions"
    )
