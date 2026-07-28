from odoo import fields, models


class PosConfig(models.Model):
    _description = 'PosConfig'
    _inherit = "pos.config"

    default_partner_id = fields.Many2one(
        comodel_name="res.partner",
        string="Cliente predeterminado",
    )
    ticofac_receipt_enabled = fields.Boolean(
        string="Tiquete fiscal TicoFac",
        default=True,
        help="Usa el diseño fiscal costarricense en el recibo impreso del POS.",
    )
    ticofac_receipt_show_qr = fields.Boolean(
        string="Mostrar QR fiscal",
        default=True,
        help="Imprime un QR con la clave electrónica del comprobante.",
    )
    ticofac_receipt_show_customer = fields.Boolean(
        string="Mostrar información del cliente",
        default=True,
    )
