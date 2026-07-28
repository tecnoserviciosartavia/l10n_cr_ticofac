from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _description = 'ResConfigSettings'
    _inherit = "res.config.settings"

    pos_default_partner_id = fields.Many2one(
        related="pos_config_id.default_partner_id",
        readonly=False,
    )
    pos_ticofac_receipt_enabled = fields.Boolean(
        related="pos_config_id.ticofac_receipt_enabled",
        readonly=False,
    )
    pos_ticofac_receipt_show_qr = fields.Boolean(
        related="pos_config_id.ticofac_receipt_show_qr",
        readonly=False,
    )
    pos_ticofac_receipt_show_customer = fields.Boolean(
        related="pos_config_id.ticofac_receipt_show_customer",
        readonly=False,
    )