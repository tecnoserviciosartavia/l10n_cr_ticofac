
from odoo import models, fields, api, _

class AccountInvoiceElectronic(models.Model):
    _description = 'AccountInvoiceElectronic'
    _inherit = "account.move"

    iva_condition = fields.Selection([
        ('gecr', 'Genera crédito IVA'),
        ('crpa', 'Genera crédito parcial del IVA'),
        ('bica', 'Capital assets'),
        ('gcnc', 'El gasto corriente no genera crédito'),
        ('prop', 'Proporcionalidad')],
        string='Condición de IVA',
        required=False,
        default='gecr',
    )

