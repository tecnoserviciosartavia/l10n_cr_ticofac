#import base64
#import datetime
#import pytz

#import re
#from xml.sax.saxutils import escape
#from lxml import etree

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import qrcode
import base64
import re
from io import BytesIO
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
#from odoo.tools.misc import get_lang
#from odoo.http import request
#from odoo.tools import html2plaintext

#from .qr_generator import GenerateQrCode
#from . import api_facturae
#from .. import extensions

#import logging
#_logger = logging.getLogger(__name__)

class AccountInvoiceElectronic(models.Model):
    _inherit = "account.move"

    show_cabys_codes_invoice_qweb = fields.Boolean(
        string="Show CABYS codes on invoice",
        default=False
        )
    qr_image = fields.Binary(
        string="QR Code",
        compute="_compute_qr_image",
        store=False,
    )

    @api.depends("number_electronic")
    def _compute_qr_image(self):
        """Genera el QR 4.4 a partir de la clave electrónica de 50 posiciones."""
        for record in self:
            record.qr_image = False
            clave = (record.number_electronic or "").strip()
            if len(clave) != 50:
                continue
            qr = qrcode.QRCode(
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=8,
                border=4,
            )
            qr.add_data(clave)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            record.qr_image = base64.b64encode(buffer.getvalue())

    def _get_name_invoice_report(self):
        """ This method need to be inherit by the localizations if they want to print a custom invoice report instead of
        the default one. For example please review the l10n_ar module """
        self.ensure_one()
        return 'l10n_cr_ticofac.report_invoice_document_fecr'
