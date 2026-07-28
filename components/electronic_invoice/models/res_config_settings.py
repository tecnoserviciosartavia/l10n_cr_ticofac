
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _description = 'ResConfigSettings'
    _inherit = 'res.config.settings'

    expense_product_id = fields.Many2one(
        comodel_name='product.product',
        company_dependent=True,
        string="Default product for expenses when loading data from XML",
        help="The default product used when loading Costa Rican digital invoice"
    )

    expense_account_id = fields.Many2one(
        comodel_name='account.account',
        company_dependent=True,
        string="Default Expense Account when loading data from XML",
        help="The expense account used when loading Costa Rican digital invoice"
    )

    expense_analytic_account_id = fields.Many2one(
        comodel_name='account.analytic.account',
        company_dependent=True,
        string="Default Analytic Account for expenses when loading data from XML",
        help="The analytic account used when loading Costa Rican digital invoice"
    )

    load_lines = fields.Boolean(
        string='Indicates if invoice lines should be load when loading a Costa Rican Digital Invoice',
        default=True
    )

    # Campos para configuración de Hacienda
    url_base = fields.Char(
        string="URL Base Hacienda",
        related="company_id.url_base",
        readonly=False
    )
    
    url_base_yo_contribuyo = fields.Char(
        string="URL Base Yo Contribuyo",
        related="company_id.url_base_yo_contribuyo",
        readonly=False
    )
    
    get_tributary_information = fields.Boolean(
        string="Obtener información tributaria",
        related="company_id.get_tributary_information",
        readonly=False
    )
    
    get_yo_contribuyo_information = fields.Boolean(
        string="Obtener información Yo Contribuyo",
        related="company_id.get_yo_contribuyo_information",
        readonly=False
    )
    
    usuario_yo_contribuyo = fields.Char(
        string="Usuario Yo Contribuyo",
        related="company_id.usuario_yo_contribuyo",
        readonly=False
    )
    
    token_yo_contribuyo = fields.Char(
        string="Token Yo Contribuyo",
        related="company_id.token_yo_contribuyo",
        readonly=False
    )

    # Este campo almacenará la referencia al medio de pago por defecto
    payment_method_default_id = fields.Many2one(
        'payment.methods',
        string="Medio de Pago por Defecto (FE CR)",
        company_dependent=True,
        help="Medio de pago predeterminado para las facturas electrónicas de Costa Rica."
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        get_param = self.env['ir.config_parameter'].sudo().get_param

        try:
            expense_account_id = int(get_param('expense_account_id')) if get_param('expense_account_id') else False
        except (TypeError, ValueError):
            expense_account_id = False

        res.update(
            expense_account_id=expense_account_id,
            load_lines=get_param('load_lines'),
            expense_product_id=int(get_param('expense_product_id')) if get_param('expense_product_id') else False,
            expense_analytic_account_id=int(get_param('expense_analytic_account_id')) if get_param(
                'expense_analytic_account_id') else False,
            payment_method_default_id=self.env.company.payment_method_default_id.id
        )
        return res

    @api.model
    def set_values(self):
        super().set_values()
        set_param = self.env['ir.config_parameter'].sudo().set_param

        if self.expense_account_id:
            set_param('expense_account_id', self.expense_account_id.id)
        set_param('load_lines', self.load_lines)

        if self.expense_product_id:
            set_param('expense_product_id', self.expense_product_id.id)
        if self.expense_analytic_account_id:
            set_param('expense_analytic_account_id', self.expense_analytic_account_id.id)
        
        self.company_id.payment_method_default_id = self.payment_method_default_id
