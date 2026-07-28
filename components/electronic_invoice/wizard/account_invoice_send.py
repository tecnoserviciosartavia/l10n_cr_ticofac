# from odoo import models
# from odoo.tools.misc import get_lang
#
#
# class AccountInvoiceSend(models.TransientModel):
#     _name = 'account.invoice.send.wizzard'
#     _description = 'Account Invoice Send'
#     _inherit = 'account.move.send'
#
#     # -------------------------------------------------------------------------
#     # PUBLIC ACTIONS
#     # -------------------------------------------------------------------------
#
#     def send_and_print_action(self):
#         self.ensure_one()
#         if self.composition_mode == 'mass_mail' and self.template_id:
#             for move in self.invoice_ids:
#                 if move.company_id.frm_ws_ambiente == 'disabled':
#                     active_records = self.env[self.model].browse(move.ids)
#                     langs = active_records.mapped('partner_id.lang')
#                     default_lang = get_lang(self.env)
#                     for lang in (set(langs) or [default_lang]):
#                         active_ids_lang = active_records.filtered(lambda r: r.partner_id.lang == lang).ids
#                         self_lang = self.with_context(active_ids=active_ids_lang, lang=lang)
#                         self_lang.onchange_template_id()
#                         self_lang._send_email()
#                 else:
#                     if move.state_tributacion == 'aceptado':
#                         move.action_invoice_sent_mass()
#         else:
#             self._send_email()
#         if self.is_print:
#             return self._print_document()
#         return {
#             'type': 'ir.actions.act_window_close'
#         }
from odoo import models, api
import xml.etree.ElementTree as etree
from xml.sax.saxutils import escape
import logging

_logger = logging.getLogger(__name__)

class IrMailServer(models.Model):
    _inherit = "ir.mail_server"
    _description = 'IR Mail Server'

    def send_email(self, message, **kwargs):
        # Guardamos la dirección del destinatario original
        original_to = message.get('To')

        # Ejecutamos el comportamiento original
        res = super(IrMailServer, self).send_email(message, **kwargs)

        # Verificamos si el mensaje contiene archivos adjuntos
        attachments = message.get_payload()
        if not isinstance(attachments, list):
            attachments = [attachments]

        # Verificamos que el correo venga del ministerio de salud
        if original_to and 'ministeriodesalud.go.cr' in original_to:
            for attach in attachments:
                if attach.get_content_type() == 'application/xml':
                    try:
                        self.env['account.move'].sudo().create_invoice_with_attamecth({
                            'filename': attach.get_filename(),
                            'content': attach.get_payload(decode=True),
                        })
                    except Exception as e:
                        _logger.error(f"[ERROR] Error procesando el XML adjunto: {e}")

        return res

class AccountMove(models.Model):
    _inherit = 'account.move'

    def create_invoice_with_attamecth(self, attach):
        content = attach['content']
        if isinstance(content, str):
            content = content.encode('utf-8')

        try:
            invoice_xml = etree.fromstring(content)
        except Exception as e:
            raise ValueError(f"Error al parsear XML: {e}")

        ns = {'d': 'https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.3/mensajeReceptor'}

        numero = invoice_xml.findtext('.//d:NumeroCedulaEmisor', namespaces=ns)
        consecutivo = invoice_xml.findtext('.//d:NumeroConsecutivo', namespaces=ns)
        clave = invoice_xml.findtext('.//d:Clave', namespaces=ns)
        fecha = invoice_xml.findtext('.//d:FechaEmisionDoc', namespaces=ns)
        monto_total = invoice_xml.findtext('.//d:TotalFactura', namespaces=ns)

        partner = self.env['res.partner'].sudo().search([
            '|',
            ('vat', '=', numero),
            ('ref', '=', numero)
        ], limit=1)

        if not partner:
            raise ValueError("No se encontró el proveedor con cédula/ref: %s" % numero)

        move = self.env['account.move'].sudo().create({
            'move_type': 'in_invoice',
            'partner_id': partner.id,
            'invoice_date': fecha,
            'ref': consecutivo,
            'name': clave,
            'invoice_line_ids': [(0, 0, {
                'name': escape("XML de factura importado automáticamente"),
                'quantity': 1,
                'price_unit': float(monto_total or 0.0),
                'account_id': self.env['account.account'].search([('user_type_id.name', '=', 'Gastos')], limit=1).id,
            })]
        })

        return move
