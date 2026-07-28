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
    pos_ticofac_receipt_show_address = fields.Boolean(
        related="pos_config_id.ticofac_receipt_show_address", readonly=False,
    )
    pos_ticofac_receipt_show_activity = fields.Boolean(
        related="pos_config_id.ticofac_receipt_show_activity", readonly=False,
    )
    pos_ticofac_receipt_show_payment = fields.Boolean(
        related="pos_config_id.ticofac_receipt_show_payment", readonly=False,
    )
    pos_ticofac_receipt_qr_label = fields.Char(
        related="pos_config_id.ticofac_receipt_qr_label", readonly=False,
    )
    pos_ticofac_receipt_qr_size = fields.Selection(
        related="pos_config_id.ticofac_receipt_qr_size", readonly=False,
    )
    pos_ticofac_receipt_legal_text = fields.Text(
        related="pos_config_id.ticofac_receipt_legal_text", readonly=False,
    )
