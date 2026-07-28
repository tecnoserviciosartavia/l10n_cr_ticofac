# -*- coding: utf-8 -*-

import logging, re
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _name = 'product.template'
    _description = 'Product Template'
    _inherit = ['product.template', ]

    cabys_product_id = fields.Many2one("cabys.producto", "Producto en el catálogo Cabys")
    cabys_code = fields.Char(related='cabys_product_id.codigo', readonly=True)
    cabys_tax = fields.Float(related='cabys_product_id.impuesto', readonly=True)


    registro_medicamento = fields.Char(string='Registro de Medicamento',)
    forma_farmaceutica_id = fields.Many2one(
        comodel_name='pharmaceutical.form',
        string='Forma Farmaceutica',
    )

    # Campo para indicar si los campos deben mostrarse
    show_fields_based_on_cabys = fields.Boolean(
        string="Mostrar Campos",
        compute="_compute_show_fields_based_on_cabys",
        store=False  # No se guarda en la base de datos, solo en memoria
    )

    @api.depends('cabys_code')
    def _compute_show_fields_based_on_cabys(self):
        for record in self:
            # Verificar si cabys_code tiene un valor válido
            if record.cabys_code and (
                record.cabys_code == '3569104990000' or
                record.cabys_code.startswith('3562') or
                record.cabys_code.startswith('3563')
            ):
                record.show_fields_based_on_cabys = True
            else:
                record.show_fields_based_on_cabys = False
            _logger.info(f"Registro {record.id}: show_fields_based_on_cabys={record.show_fields_based_on_cabys}")

    @api.onchange('cabys_code')
    def _onchange_code_cabys(self):
        _logger.info(f"Registro {self.id}: code_cabys={self.cabys_code}")
        self._compute_show_fields_based_on_cabys()

    @api.onchange('cabys_product_id')
    def _onchange_cabys_product_id(self):
        if self.cabys_product_id:
            # Asignar automáticamente el impuesto del producto basado en cabys_tax
            tax = self.cabys_tax
            if tax:
                # Buscar el impuesto correspondiente en el sistema
                tax_record = self.env['account.tax'].search([('amount', '=', tax)], limit=1)
                if tax_record:
                    self.taxes_id = [(6, 0, tax_record.ids)]
                    _logger.info(f"Impuesto {tax_record.name} asignado automáticamente al producto {self.id}")
                else:
                    _logger.warning(f"No se encontró un impuesto con el valor {tax} para el producto {self.id}")
