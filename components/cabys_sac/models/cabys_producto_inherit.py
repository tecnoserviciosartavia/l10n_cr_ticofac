from odoo import models, api
import re


class CabysProductoInherit(models.Model):
    _inherit = 'cabys.producto'

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, order=None, name_get_uid=None):
        """Permite buscar cabys.producto también por código SAC equivalente.
        Si el usuario escribe un código SAC, se buscan equivalencias y se
        incluyen los productos CABYS relacionados en el dominio de búsqueda.
        """
        args = args or []
        domain = list(args)

        # Base: buscar por nombre/código CABYS
        base_domain = ['|', ('name', operator, name or ''), ('codigo', operator, name or '')] if name else []

        # Extensión: buscar por equivalencia SAC
        sac_ids = []
        if name:
            clean = re.sub(r"\D", "", name or "")
            eqrecs = self.env['cabys.sac.equivalence'].search(['|', ('sac_code', operator, name), ('sac_code_clean', operator, clean)], limit=limit)
            if eqrecs:
                sac_ids = eqrecs.mapped('cabys_product_id').ids
        sac_domain = [('id', 'in', sac_ids)] if sac_ids else []

        # Combinar dominios con OR cuando haya término de búsqueda
        if name:
            if sac_domain:
                domain = ['|'] + base_domain + sac_domain + list(args)
            else:
                domain = base_domain + list(args)

        return self._search(domain, limit=limit, order=order)

    @api.model
    def name_search(self, name='', args=None, operator='ilike', limit=100):
        """Asegura que el Many2one encuentre por CABYS o por SAC equivalente."""
        ids = self._name_search(name=name, args=args, operator=operator, limit=limit)
        recs = self.browse(ids)
        return recs.name_get()
