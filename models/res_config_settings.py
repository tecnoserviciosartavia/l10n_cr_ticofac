from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"
    ticofac_company_vat = fields.Char(
        related="company_id.vat",
        string="Identificación de la compañía",
        readonly=False,
    )
    ticofac_invoice_is_electronic = fields.Boolean(related="company_id.invoice_is_electronic", readonly=False)
    ticofac_commercial_name = fields.Char(related="company_id.commercial_name", readonly=False)
    ticofac_legal_name = fields.Char(related="company_id.legal_name", readonly=False)
    ticofac_identification_id = fields.Many2one(related="company_id.identification_id", readonly=False)
    ticofac_activity_id = fields.Many2one(related="company_id.activity_id", readonly=False)
    ticofac_country_id = fields.Many2one(related="company_id.country_id", readonly=False)
    ticofac_state_id = fields.Many2one(related="company_id.state_id", readonly=False)
    ticofac_county_id = fields.Many2one(related="company_id.county_id", readonly=False)
    ticofac_district_id = fields.Many2one(related="company_id.district_id", readonly=False)
    ticofac_neighborhood_id = fields.Many2one(related="company_id.neighborhood_id", readonly=False)
    ticofac_zip = fields.Char(related="company_id.zip", readonly=True)
    ticofac_street = fields.Char(related="company_id.street", readonly=False)
    ticofac_environment = fields.Selection(related="company_id.frm_ws_ambiente", readonly=False)
    ticofac_hacienda_user = fields.Char(related="company_id.frm_ws_identificador", readonly=False)
    ticofac_hacienda_password = fields.Char(related="company_id.frm_ws_password", readonly=False)
    ticofac_signature = fields.Binary(related="company_id.signature", readonly=False)
    ticofac_certificate_pin = fields.Char(related="company_id.frm_pin", readonly=False)
    ticofac_certificate_expiration = fields.Datetime(related="company_id.date_expiration_sign", readonly=True)
    ticofac_provider_type = fields.Selection(related="company_id.invoice_provider_type", readonly=False)
    ticofac_provider_identification = fields.Char(related="company_id.invoice_provider_identification", readonly=False)
    ticofac_cabys_product_id = fields.Many2one(related="company_id.cabys_product_id", readonly=False)
    ticofac_import_bill_automatic = fields.Boolean(related="company_id.import_bill_automatic", readonly=False)
    ticofac_import_bill_mail_server_id = fields.Many2one(related="company_id.import_bill_mail_server_id", readonly=False)
    ticofac_import_bill_folder = fields.Char(related="company_id.import_bill_folder_import", readonly=False)
    ticofac_import_bill_journal_id = fields.Many2one(related="company_id.import_bill_journal_id", string="Diario de importación de facturas", readonly=False)
    ticofac_import_bill_product_id = fields.Many2one(related="company_id.import_bill_product_id", readonly=False)
    ticofac_import_bill_account_id = fields.Many2one(
        related="company_id.import_bill_account_id",
        string="Cuenta de gasto para importación Ticofac",
        readonly=False,
    )
    ticofac_import_bill_account_analytic_id = fields.Many2one(related="company_id.import_bill_account_analytic_id", readonly=False)
    ticofac_invoice_color = fields.Selection(related="company_id.cr_invoice_color", readonly=False)
    ticofac_bank_account_crc = fields.Html(related="company_id.html_bank_account1", readonly=False)
    ticofac_bank_account_usd = fields.Html(related="company_id.html_bank_account2", readonly=False)

    @api.onchange("ticofac_signature", "ticofac_certificate_pin")
    def _onchange_ticofac_certificate(self):
        from ..components.electronic_invoice.models import api_facturae
        for settings in self:
            if settings.ticofac_signature and settings.ticofac_certificate_pin:
                try:
                    settings.ticofac_certificate_expiration = (
                        api_facturae.p12_expiration_date(
                            settings.ticofac_signature,
                            settings.ticofac_certificate_pin,
                        )
                    )
                except Exception:
                    settings.ticofac_certificate_expiration = False
            else:
                settings.ticofac_certificate_expiration = False

    def _ticofac_open_record(self, xmlid, res_model, title):
        record = self.env.ref(xmlid)
        views = []
        if res_model == "mail.template":
            views = [(self.env.ref("mail.email_template_form").id, "form")]
        return {
            "type": "ir.actions.act_window",
            "name": title,
            "res_model": res_model,
            "res_id": record.id,
            "view_mode": "form",
            "views": views or [(False, "form")],
            "target": "current",
        }

    def action_ticofac_test_token(self):
        self.ensure_one()
        if self.ticofac_environment == "disabled":
            from odoo.exceptions import UserError
            raise UserError("Seleccione el ambiente de Pruebas o Producción.")
        if not self.ticofac_hacienda_user or not self.ticofac_hacienda_password:
            from odoo.exceptions import UserError
            raise UserError("Ingrese el usuario y la contraseña de Hacienda.")
        from ..components.electronic_invoice.models import api_facturae
        token = api_facturae.get_token_hacienda(
            self.env.user, self.ticofac_environment, force_refresh=True
        )
        if not token:
            from odoo.exceptions import UserError
            raise UserError("Hacienda no devolvió un token de autenticación.")
        environment_name = {
            "api-stag": "Pruebas",
            "api-prod": "Producción",
        }.get(self.ticofac_environment, self.ticofac_environment)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Autenticación correcta",
                "message": f"Hacienda aceptó las credenciales en el ambiente {environment_name}.",
                "type": "success",
            },
        }

    def action_ticofac_validate_certificate(self):
        self.ensure_one()
        expiration = self.company_id.get_expiration_date()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Certificado válido",
                "message": (
                    "La llave criptográfica vence el "
                    f"{fields.Datetime.to_string(expiration)} (UTC)."
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_ticofac_edit_invoice_pdf(self):
        return self._ticofac_open_record(
            "l10n_cr_ticofac.report_invoice_document_fecr",
            "ir.ui.view",
            "Formato PDF de factura electrónica",
        )

    def action_ticofac_edit_customer_email(self):
        return self._ticofac_open_record(
            "account.email_template_edi_invoice",
            "mail.template",
            "Correo de factura a clientes",
        )

    def action_ticofac_edit_vendor_email(self):
        return self._ticofac_open_record(
            "l10n_cr_ticofac.email_template_invoice_vendor",
            "mail.template",
            "Correo de confirmación a proveedores",
        )

    def action_ticofac_test_hacienda(self):
        return self.company_id.action_get_economic_activities()
