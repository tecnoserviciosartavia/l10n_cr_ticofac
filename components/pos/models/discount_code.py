# -*- coding: utf-8 -*-
"""
Discount Code POS Extension

This module extends discount.code model to make it available in POS.
"""
from odoo import api, models


class DiscountCodePOS(models.Model):
    """Extend discount.code to load in POS"""

    _inherit = ["discount.code", "pos.load.mixin"]
    _name = "discount.code"

    @api.model
    def _load_pos_data_domain(self, data):
        """Domain to filter which discount codes load into POS"""
        return [("active", "=", True)]

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Fields to load into POS frontend"""
        return ["id", "code", "name", "active"]
