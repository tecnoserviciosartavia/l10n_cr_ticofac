# -*- coding:utf-8 -*-
import logging
import email
import base64
import pathlib
import zipfile
import io
from lxml import etree
from datetime import datetime
from ...electronic_invoice.models.api_facturae import load_xml_data

import re

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

class FetchmailServer(models.Model):
    _description = 'FetchmailServer'
    _inherit = 'fetchmail.server'

    def fetch_mail(self, raise_exception=False):
        res_companies_ids = self.env['res.company'].sudo().search([])
        for res_company_id in res_companies_ids:
            if res_company_id.import_bill_automatic:
                additionnal_context = {'fetchmail_cron_running': True}
                MailThread = self.env['mail.thread']
                server = res_company_id.import_bill_mail_server_id
                additionnal_context['fetchmail_server_id'] = server.id
                additionnal_context['server_type'] = server.server_type

                _logger.info('Start checking for new emails on %s server %s', server.server_type, server.name)
                count, failed = 0, 0
                imap_server = None

                if server.server_type == 'imap':
                    try:
                        imap_server = server.connect()
                        imap_server.select(mailbox=res_company_id.import_bill_folder_import or 'INBOX')
                        result, data = imap_server.search(None, '(UNSEEN)')
                        if not data[0]:
                            _logger.info("Empty Folder (Stop Execute)")
                            return
                        for num in data[0].split():
                            result, data = imap_server.fetch(num, '(RFC822)')
                            imap_server.store(num, '-FLAGS', '\\Seen')
                            message = data[0][1]
                            try:
                                if isinstance(message, str):
                                    message = message.encode('utf-8')
                                message = email.message_from_bytes(message, policy=email.policy.SMTP)
                                msg = MailThread.message_parse(message, save_original=False)

                                _logger.info("------ Process Message --------")
                                _logger.info("Subject : %s ", msg.get('subject', ''))
                                _logger.info("From: %s ", msg.get('from', ''))
                                _logger.info("To: %s ", msg.get('to', ''))

                                result = self.create_invoice_with_attamecth(msg, res_company_id)
                                if result and not isinstance(result, bool):
                                    if not server.original:
                                        imap_server.store(num, '+FLAGS', '\\Deleted')
                                    _logger.info("Invoice created correctly %s", str(result))
                                elif result:
                                    if not server.original:
                                        imap_server.store(num, '+FLAGS', '\\Deleted')
                                    _logger.info("Repeated Invoice")
                                else:
                                    _logger.info("Ignore email")
                            except Exception as e:
                                _logger.exception("Failed to process mail.")
                                failed += 1
                            imap_server.store(num, '+FLAGS', '\\Seen')
                            self._cr.commit()
                            count += 1
                            _logger.info("------ End Process Message -------")

                        _logger.info("Fetched %d email(s) on %s server %s; %d succeeded, %d failed.", count, server.server_type, server.name, (count - failed), failed)
                    except Exception as e:
                        _logger.exception("General failure when trying to fetch mail.")
                    finally:
                        if imap_server:
                            try:
                                moves_to_delete = self.env['account.move'].search([
                                    ('partner_id', '=', False),
                                    ('ref', '=', False),
                                    ('state', '=', 'draft'),
                                    ('move_type', '=', 'in_invoice'),
                                    ('line_ids', '=', False),
                                ])
                                _logger.info('Se encontraron %d documentos creados erroneamente, se eliminarán.', len(moves_to_delete))
                                moves_to_delete.unlink()
                            except Exception:
                                _logger.warning("Error al eliminar facturas incorrectas. Se intentará en la próxima ejecución.")

                            imap_server.close()
                            imap_server.logout()
                    server.write({'date': fields.Datetime.now()})
                else:
                    _logger.info("Only Support for IMAP Server")
                    server.write({'date': fields.Datetime.now()})
                    return super(FetchmailServer, self).fetch_mail()

    @staticmethod
    def is_xml_file_in_attachment(attach):
        file_name = attach.fname or 'item.ignore'
        return pathlib.Path(file_name.upper()).suffix == '.XML'

    def get_bill_exist_or_false(self, invoice_xml):
        namespaces = invoice_xml.nsmap
        inv_xmlns = namespaces.pop(None)
        namespaces['inv'] = inv_xmlns
        electronic_number = invoice_xml.xpath("inv:Clave", namespaces=namespaces)[0].text
        domain = [('number_electronic', '=', electronic_number)]
        return self.env['account.move'].search(domain, limit=1)

    def create_ir_attachment_invoice(self, invoice, attach, mimetype):
        content = attach['content']
        if isinstance(content, str):
            content = content.encode('utf-8')
        return self.env['ir.attachment'].create({
            'name': attach['fname'],
            'type': 'binary',
            'datas': base64.b64encode(content),
            'store_fname': attach['fname'],
            'res_model': 'account.move',
            'res_id': invoice.id,
            'mimetype': mimetype
        })

    def extract_attachments_from_zip(self, content):
        attachments = []
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            for file_info in z.infolist():
                with z.open(file_info) as file:
                    attachments.append({
                        'fname': file_info.filename,
                        'content': file.read()
                    })
        return attachments

    def create_invoice_with_attamecth(self, msg, company_id):
        attachments = []

        for attach in msg.get('attachments'):
            fname = attach.fname or 'item.ignore'
            suffix = pathlib.Path(fname.lower()).suffix
            if suffix == '.zip':
                try:
                    content = attach.content if isinstance(attach.content, bytes) else attach.content.encode('utf-8')
                    extracted = self.extract_attachments_from_zip(content)
                    attachments.extend(extracted)
                    _logger.info("Archivo ZIP extraído: %s", fname)
                except Exception as e:
                    _logger.warning("Error al extraer ZIP %s: %s", fname, e)
            else:
                attachments.append({
                    'fname': fname,
                    'content': attach.content,
                })

        for attach in attachments:
            if pathlib.Path(attach['fname'].upper()).suffix != '.XML':
                continue
            try:
                attachencode = base64.encodebytes(attach['content']) if isinstance(attach['content'], bytes) else base64.encodebytes(attach['content'].encode('utf-8'))
                invoice_xml = etree.fromstring(base64.b64decode(attachencode))
                match = re.search('FacturaElectronica|NotaCreditoElectronica|NotaDebitoElectronica|TiqueteElectronico|MensajeHacienda', invoice_xml.tag)
                if not match:
                    _logger.info("Documento con etiqueta desconocida: %s", invoice_xml.tag)
                    continue
                document_type = match.group(0)

                if document_type == 'TiqueteElectronico':
                    _logger.info("Este es un Tiquete Electronico no válido para impuestos.")
                    continue

                exist_invoice = self.get_bill_exist_or_false(invoice_xml)

                if document_type == 'MensajeHacienda' and exist_invoice:
                    attachment_id = self.create_ir_attachment_invoice(exist_invoice, attach, 'application/xml')
                    exist_invoice.message_post(attachment_ids=[attachment_id.id])
                    _logger.info('Mensaje Hacienda agregado a factura existente.')
                    return exist_invoice

                if document_type in ['FacturaElectronica', 'NotaCreditoElectronica'] and exist_invoice:
                    _logger.info("Factura duplicada (%s), se ignorará.", exist_invoice.ref)
                    return True

                type_invoice = 'in_invoice' if document_type in ['FacturaElectronica', 'NotaDebitoElectronica'] else 'in_refund'

                # Crear factura usando directamente el ORM de Odoo
                vals = {
                    'move_type': type_invoice,
                    'journal_id': company_id.import_bill_journal_id.id,
                }
                invoice = self.env['account.move'].create(vals)

                invoice.fname_xml_supplier_approval = attach['fname']
                content_supplier_approval = attach['content']
                if isinstance(content_supplier_approval, str):
                    content_supplier_approval = content_supplier_approval.encode('utf-8')

                # Before storing, sanitize XML to avoid parser crashes in api_facturae
                # Some Importe/Impuesto nodes (e.g., impuesto tipo 05) may not include a <Tarifa> node.
                # The upstream parser assumes <Tarifa> exists and will IndexError. We add a default <Tarifa>0.0
                # when missing. This edit stays within this module as requested.
                try:
                    invoice_xml = etree.fromstring(content_supplier_approval)
                    nsmap = invoice_xml.nsmap.copy()
                    inv_xmlns = nsmap.pop(None, None)
                    if inv_xmlns:
                        ns = {'inv': inv_xmlns}
                    else:
                        ns = {k: v for k, v in nsmap.items()}

                    added = 0
                    # Find Impuesto nodes and ensure they have a Tarifa child
                    impuesto_nodes = invoice_xml.xpath('//inv:Impuesto', namespaces=ns)
                    for imp in impuesto_nodes:
                        tarifa_nodes = imp.xpath('inv:Tarifa', namespaces=ns)
                        if not tarifa_nodes:
                            # create Tarifa element in the same namespace
                            if inv_xmlns:
                                tarifa_tag = etree.QName(inv_xmlns, 'Tarifa')
                                new_el = etree.Element(tarifa_tag.text)
                            else:
                                new_el = etree.Element('Tarifa')
                            new_el.text = '0.0'
                            # insert before Monto if exists, else append
                            monto_nodes = imp.xpath('inv:Monto', namespaces=ns)
                            if monto_nodes:
                                imp.insert(list(imp).index(monto_nodes[0]), new_el)
                            else:
                                imp.append(new_el)
                            added += 1

                    if added:
                        _logger.info('ImportVendorBills - added %d missing <Tarifa> nodes to XML %s', added, attach['fname'])
                        # Serialize back to bytes
                        content_supplier_approval = etree.tostring(invoice_xml, encoding='utf-8', xml_declaration=False)
                except Exception as e:
                    _logger.warning('ImportVendorBills - unable to sanitize XML before import: %s', e)

                # Store as standard base64 (no extra newlines control)
                invoice.xml_supplier_approval = base64.b64encode(content_supplier_approval)

                # Debug logging: registrar metadatos antes de procesar
                try:
                    _logger.info('ImportVendorBills - procesando XML %s (size=%s bytes) para company %s', attach['fname'], len(content_supplier_approval), company_id.name)
                except Exception:
                    _logger.info('ImportVendorBills - procesando XML %s', attach['fname'])

                # Llamada al parser con manejo de errores para no dejar facturas vacías
                try:
                    load_xml_data(
                        invoice, True,
                        company_id.import_bill_account_id,
                        company_id.import_bill_product_id,
                        company_id.import_bill_account_analytic_id
                    )
                except Exception as e:
                    # Registrar excepción completa y eliminar factura creada para evitar documentos huérfanos
                    _logger.exception('Error al cargar datos del XML en la factura %s: %s', invoice.id if invoice and invoice.id else 'unknown', e)
                    try:
                        # Intentar eliminar la factura creada sin líneas
                        if invoice and invoice.exists():
                            invoice.unlink()
                            _logger.info('Factura eliminada porque falló la carga del XML: %s', attach['fname'])
                    except Exception as e2:
                        _logger.exception('No fue posible eliminar la factura tras error de importación: %s', e2)
                    continue

                list_attachment = [self.create_ir_attachment_invoice(invoice, attach, 'application/xml').id]
                for a in attachments:
                    suffix = pathlib.Path(a['fname'].upper()).suffix
                    if suffix == '.XML':
                        invoice_xml = etree.fromstring(a['content'])
                        if re.search('MensajeHacienda', invoice_xml.tag):
                            list_attachment.append(self.create_ir_attachment_invoice(invoice, a, 'application/xml').id)
                    elif suffix == '.PDF':
                        list_attachment.append(self.create_ir_attachment_invoice(invoice, a, 'application/pdf').id)

                invoice.message_post(attachment_ids=list_attachment)
                return invoice
            except Exception as e:
                _logger.warning("Error procesando archivo XML: %s", e)
                continue
        return False