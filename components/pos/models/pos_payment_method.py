import unicodedata

from odoo import api, fields, models


class PosPaymentMethod(models.Model):
    _description = 'PosPaymentMethod'
    _inherit = "pos.payment.method"

    account_payment_method_id = fields.Many2one(
        "payment.methods",
        string="Medio de pago de Hacienda",
        help="Código de medio de pago que TicoFac enviará a Hacienda.",
    )

    @api.model
    def _ticofac_payment_sequence_from_name(self, name):
        normalized = unicodedata.normalize("NFKD", name or "")
        normalized = "".join(
            character for character in normalized
            if not unicodedata.combining(character)
        ).lower()
        aliases = (
            (("sinpe",), "06"),
            (("tarjeta", "card"), "02"),
            (("cheque", "check"), "03"),
            (("transferencia", "transfer", "deposito"), "04"),
            (("tercero",), "05"),
            (("plataforma", "digital"), "07"),
            (("efectivo", "cash"), "01"),
            (("cuenta de cliente", "customer account", "credito", "credit"), "99"),
        )
        for names, sequence in aliases:
            if any(alias in normalized for alias in names):
                return sequence
        return "99"

    def _ticofac_assign_hacienda_payment_method(self):
        catalog = {
            method.sequence: method
            for method in self.env["payment.methods"].sudo().search(
                [("active", "=", True)]
            )
        }
        for payment_method in self.filtered(
            lambda method: not method.account_payment_method_id
        ):
            sequence = self._ticofac_payment_sequence_from_name(payment_method.name)
            hacienda_method = catalog.get(sequence)
            if hacienda_method:
                payment_method.sudo().account_payment_method_id = hacienda_method
        return True

    @api.model_create_multi
    def create(self, vals_list):
        payment_methods = super().create(vals_list)
        payment_methods._ticofac_assign_hacienda_payment_method()
        return payment_methods
