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
    ticofac_receipt_show_address = fields.Boolean(
        string="Mostrar dirección del emisor", default=True,
    )
    ticofac_receipt_show_activity = fields.Boolean(
        string="Mostrar actividad económica", default=True,
    )
    ticofac_receipt_show_payment = fields.Boolean(
        string="Mostrar condición, pago y moneda", default=True,
    )
    ticofac_receipt_qr_label = fields.Char(
        string="Texto bajo el QR",
        default="Escanee para consultar la clave electrónica",
    )
    ticofac_receipt_qr_size = fields.Selection(
        [("small", "Pequeño"), ("medium", "Mediano"), ("large", "Grande")],
        string="Tamaño del QR", default="large", required=True,
    )
    ticofac_receipt_legal_text = fields.Text(
        string="Texto legal",
        default=(
            "Documento emitido conforme a la resolución\n"
            "N.° MH-DGT-RES-0027-2024 del 13 de noviembre de 2024.\n"
            "Versión 4.4\n"
            "Conserve este documento y los archivos XML asociados."
        ),
    )
