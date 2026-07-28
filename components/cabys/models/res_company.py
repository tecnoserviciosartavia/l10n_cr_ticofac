# -*- coding: utf-8 -*-

import logging
from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):

    _inherit = 'res.company'
    _description = 'Product Company'

    cabys_product_id = fields.Many2one("cabys.producto", "Código Cabys para productos sin codigo asignado")
