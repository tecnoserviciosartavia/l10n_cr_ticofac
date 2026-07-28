import logging
from odoo import models, fields, api, _
_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    chK_invoice_to_hacienda = fields.Boolean(string='No permitir enviar facturas a Hacienda', related='journal_id.chK_invoice_to_hacienda')

    def generate_and_send_invoices(self, invoices):
        invoices_send = []
        for inv in invoices:
            if inv.journal_id.chK_invoice_to_hacienda:
                inv.state_tributacion = 'na'
                _logger.info('Factura no enviada a Hacienda por configuración de Diario:%s', inv.name)
                continue
            else:
                invoices_send.append(inv.id)
        invoices = self.browse(invoices_send)
        return super(AccountMove, self).generate_and_send_invoices(invoices)

