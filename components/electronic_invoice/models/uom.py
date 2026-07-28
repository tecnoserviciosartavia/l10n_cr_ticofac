from odoo import models, fields


class UoM(models.Model):
    _description = 'UoM'
    _inherit = "uom.uom"

    code = fields.Char()
