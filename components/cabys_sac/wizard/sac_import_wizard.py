from odoo import api, fields, models, _
from odoo.exceptions import UserError
import pandas as pd
import base64
import urllib.request
import tempfile
import os
import logging

_logger = logging.getLogger(__name__)

EXPECTED_SHEET = 'SAC-Cabys'
COL_SAC = 'SAC versión 2017'
COL_CABYS = 'Código Cabys equivalente al SAC'


class CabysSACImportWizard(models.TransientModel):
    _name = 'cabys.sac.import.wizard'
    _description = 'Importar equivalencias SAC 2017 - CABYS desde Excel'

    notes = fields.Text(string='Descripción', readonly=True)
    button_enable = fields.Boolean()
    file_url = fields.Char(
        string='URL archivo Equivalencias',
        default='https://www.bccr.fi.cr/indicadores-economicos/cabys/Equivalencias-entre-clasificaciones.xlsx',
    )
    excel_file = fields.Binary(string='Archivo de Excel', attachment=True, copy=False)

    def action_download(self):
        try:
            _logger.info('Descargando archivo de equivalencias: %s', self.file_url)
            response = urllib.request.urlopen(self.file_url)
            self.excel_file = base64.b64encode(response.read())
            self.onchange_excel_file()
        except Exception as e:
            raise UserError(_('No se pudo descargar el archivo: %s') % e)

        return {
            'name': _('Importar Equivalencias SAC - CABYS'),
            'type': 'ir.actions.act_window',
            'res_model': 'cabys.sac.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
        }

    def _read_dataframe(self, temp_path):
        """Leer Excel detectando dinámicamente la fila de encabezados y columnas requeridas."""
        import unicodedata

        def _norm(s):
            if s is None:
                return ''
            s = str(s)
            s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
            return s.strip().lower()

        norm_sac = _norm(COL_SAC)
        norm_cabys = _norm(COL_CABYS)

        try:
            df_raw = pd.read_excel(temp_path, sheet_name=EXPECTED_SHEET, header=None, dtype=str)
        except Exception as e:
            raise UserError(_('Error al leer la hoja "%s": %s') % (EXPECTED_SHEET, e))

        header_idx = None
        max_scan = min(30, len(df_raw))
        for i in range(max_scan):
            row_vals = [str(v) if v is not None else '' for v in list(df_raw.iloc[i])]
            row_norm = [_norm(v) for v in row_vals]
            has_sac = any(rv == norm_sac or ('sac' in rv and '2017' in rv) for rv in row_norm)
            has_cabys = any(rv == norm_cabys or ('cabys' in rv and 'equivalente' in rv) for rv in row_norm)
            if has_sac and has_cabys:
                header_idx = i
                break

        if header_idx is None:
            sample_cols = [str(c) for c in list(df_raw.iloc[0])]
            raise UserError(_(
                'El archivo no contiene las columnas requeridas: "%s" y "%s". Columnas encontradas: %s'
            ) % (COL_SAC, COL_CABYS, ', '.join([c for c in sample_cols if c and c != 'nan'])))

        headers = [str(v).strip() if v is not None else '' for v in list(df_raw.iloc[header_idx])]
        df = df_raw.iloc[header_idx + 1:].reset_index(drop=True).copy()
        df.columns = headers

        cols_map = {_norm(c): c for c in df.columns}
        sac_col = cols_map.get(norm_sac)
        cabys_col = cols_map.get(norm_cabys)
        if not sac_col:
            sac_col = next((c for c in df.columns if 'sac' in _norm(c) and '2017' in _norm(c)), None)
        if not cabys_col:
            cabys_col = next((c for c in df.columns if 'cabys' in _norm(c) and 'equivalente' in _norm(c)), None)
        if not sac_col or not cabys_col:
            raise UserError(_(
                'No se pudieron identificar las columnas SAC y CABYS en el encabezado. Detectadas: %s'
            ) % ', '.join(df.columns))

        df[sac_col] = df[sac_col].astype(str).str.strip()
        df[cabys_col] = df[cabys_col].astype(str).str.strip()
        df = df[(df[sac_col] != '') & (df[cabys_col] != '')]

        if sac_col != COL_SAC or cabys_col != COL_CABYS:
            df = df.rename(columns={sac_col: COL_SAC, cabys_col: COL_CABYS})

        return df

    def _analyze(self):
        news, updates, skips = [], [], []
        temp_name = None
        try:
            binary = base64.b64decode(self.excel_file)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as f:
                f.write(binary)
                temp_name = f.name
            df = self._read_dataframe(temp_name)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

        # Determinar cambios
        Equiv = self.env['cabys.sac.equivalence']
        for idx, row in df.iterrows():
            sac = (row.get(COL_SAC) or '').strip()
            cabys_code = (row.get(COL_CABYS) or '').strip()
            if not sac or not cabys_code:
                continue
            cabys = self.env['cabys.producto'].search([('codigo', '=', cabys_code)], limit=1)
            if not cabys:
                skips.append((sac, cabys_code, 'Código Cabys no encontrado'))
                continue
            rec = Equiv.search([('sac_code', '=', sac)], limit=1)
            if rec:
                if rec.cabys_product_id.id != cabys.id:
                    updates.append((sac, rec.cabys_code, cabys_code))
                else:
                    # Sin cambios
                    pass
            else:
                news.append((sac, cabys_code))
        return news, updates, skips

    @api.onchange('excel_file')
    def onchange_excel_file(self):
        if not self.excel_file:
            self.notes = _('Suba el archivo o use el botón para descargarlo desde el BCCR.')
            self.button_enable = False
            return
        try:
            news, updates, skips = self._analyze()
            msg = _('Se detectaron los siguientes cambios potenciales:\n')
            msg += _('%s nuevas equivalencias\n') % len(news)
            msg += _('%s equivalencias a actualizar\n') % len(updates)
            if skips:
                msg += _('%s filas serán omitidas (p. ej., códigos Cabys inexistentes)\n') % len(skips)
            self.notes = msg
            self.button_enable = True
        except Exception as e:
            self.notes = _('Error al analizar el archivo: %s') % e
            self.button_enable = False

    def action_import(self):
        if not self.excel_file:
            raise UserError(_('Debe adjuntar o descargar un archivo para importar.'))
        temp_name = None
        try:
            binary = base64.b64decode(self.excel_file)
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as f:
                f.write(binary)
                temp_name = f.name
            df = self._read_dataframe(temp_name)

            Equiv = self.env['cabys.sac.equivalence']
            news_cnt = updates_cnt = 0
            for idx, row in df.iterrows():
                sac = (row.get(COL_SAC) or '').strip()
                cabys_code = (row.get(COL_CABYS) or '').strip()
                if not sac or not cabys_code:
                    continue
                cabys = self.env['cabys.producto'].search([('codigo', '=', cabys_code)], limit=1)
                if not cabys:
                    continue
                rec = Equiv.search([('sac_code', '=', sac)], limit=1)
                vals = {
                    'sac_code': sac,
                    'cabys_product_id': cabys.id,
                }
                if rec:
                    if rec.cabys_product_id.id != cabys.id:
                        rec.write({'cabys_product_id': cabys.id})
                        updates_cnt += 1
                else:
                    Equiv.create(vals)
                    news_cnt += 1

            self.notes = _('Importación completada. Nuevos: %s, Actualizados: %s') % (news_cnt, updates_cnt)
            self.button_enable = False
        except Exception as e:
            raise UserError(_('Error al importar: %s') % e)
        finally:
            if temp_name and os.path.exists(temp_name):
                os.unlink(temp_name)

        return {
            'name': _('Equivalencias SAC - CABYS importadas'),
            'type': 'ir.actions.act_window',
            'res_model': 'cabys.sac.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
        }
