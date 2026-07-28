# -*- coding: utf-8 -*-

from odoo import api, fields, models
import logging

from werkzeug.debug.repr import helper

_logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    chK_invoice_to_hacienda = fields.Boolean(string='Diario fiscalizado?')








