from odoo import models, fields, api


class ProductTemplateCabysSac(models.Model):
    _inherit = 'product.template'

    # Campo auxiliar para mostrar/ocultar el buscador por SAC
    show_sac_equivalence = fields.Boolean(
        string='Mostrar búsqueda por SAC',
        compute='_compute_show_sac_equivalence',
        store=False,
    )

    # Campo de búsqueda por equivalencia SAC → al seleccionar, asigna el Cabys
    sac_equivalence_id = fields.Many2one(
        comodel_name='cabys.sac.equivalence',
        string='Equivalencia SAC',
        help='Busca por código SAC 2017 y asigna el CABYS equivalente.',
    )

    @api.depends('company_id')
    def _compute_show_sac_equivalence(self):
        ICP = self.env['ir.config_parameter'].sudo()
        enabled = ICP.get_param('l10n_cr_ticofac.enable_cabys_sac_search', default='0')
        enabled = True if str(enabled).lower() in ('1', 'true', 'yes') else False
        for rec in self:
            rec.show_sac_equivalence = enabled

    @api.onchange('sac_equivalence_id')
    def _onchange_sac_equivalence_id(self):
        for rec in self:
            if rec.sac_equivalence_id and rec.sac_equivalence_id.cabys_product_id:
                rec.cabys_product_id = rec.sac_equivalence_id.cabys_product_id.id
