# -*- coding: utf-8 -*-
"""
POS Order Line Extension for Costa Rica Electronic Invoicing

This module extends pos.order.line to support discount codes required by
Costa Rica's electronic invoicing (FE) regulations.
"""
from odoo import api, fields, models


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    discount_code_id = fields.Many2one(
        comodel_name="discount.code",
        string="Discount Code",
        help="Discount code required for FE (Electronic Invoice) when a discount is applied",
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        """Add discount_code_id to fields loaded in POS"""
        fields = super()._load_pos_data_fields(config_id)
        fields.append("discount_code_id")
        return fields

    def _export_for_ui(self, orderline):
        """Include discount_code_id when exporting orderline data to POS UI"""
        result = super()._export_for_ui(orderline)
        result["discount_code_id"] = (
            orderline.discount_code_id.id if orderline.discount_code_id else False
        )
        return result
