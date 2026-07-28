# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
import logging
import time

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model
    def cron_run_economic_activities(self):
        """
        Método que será ejecutado por el cron job.
        Filtra contactos sin actividades económicas pero con identificación
        y ejecuta la obtención automática de actividades económicas.
        """
        try:
            # Filtrar contactos según los criterios especificados
            domain = [
                "&",
                ("activity_id", "=", False),
                ("identification_id", "!=", False)
            ]

            partners = self.search(domain, limit=50)  # Limitar a 50 por ejecución para evitar rate limiting

            _logger.info(f'Cron Economic Activities: Procesando {len(partners)} contactos')

            processed_count = 0
            error_count = 0
            rate_limit_count = 0

            for partner in partners:
                try:
                    # Agregar delay entre peticiones para evitar rate limiting
                    if processed_count > 0:
                        time.sleep(2)  # 2 segundos entre peticiones

                    # Ejecutar la acción para obtener actividades económicas
                    result = partner.action_get_economic_activities()

                    if isinstance(result, dict) and 'warning' in result:
                        warning_msg = result["warning"].get("message", "Sin mensaje")
                        if "Too Many Requests" in warning_msg or "429" in warning_msg:
                            rate_limit_count += 1
                            _logger.warning(f'Rate limit alcanzado. Pausando por 30 segundos...')
                            time.sleep(30)  # Pausa más larga cuando hay rate limit
                            # Intentar una vez más después de la pausa
                            try:
                                result = partner.action_get_economic_activities()
                                if not (isinstance(result, dict) and 'warning' in result):
                                    processed_count += 1
                                    _logger.debug(f'Actividades económicas actualizadas para: {partner.name}')
                                else:
                                    error_count += 1
                                    _logger.warning(
                                        f'Segundo intento falló para contacto {partner.name} (ID: {partner.id}): {result["warning"].get("message", "Sin mensaje")}')
                            except Exception as e:
                                error_count += 1
                                _logger.error(
                                    f'Error en segundo intento para contacto {partner.name} (ID: {partner.id}): {str(e)}')
                        else:
                            _logger.warning(
                                f'Advertencia para contacto {partner.name} (ID: {partner.id}): {warning_msg}')
                            error_count += 1
                    elif result is True or result is None:
                        processed_count += 1
                        _logger.debug(f'Actividades económicas actualizadas para: {partner.name}')
                    else:
                        processed_count += 1
                        _logger.debug(f'Actividades económicas actualizadas para: {partner.name}')

                except Exception as e:
                    error_count += 1
                    _logger.error(f'Error procesando contacto {partner.name} (ID: {partner.id}): {str(e)}')

            _logger.info(
                f'Cron Economic Activities completado: {processed_count} exitosos, {error_count} errores, {rate_limit_count} rate limits')

        except Exception as e:
            _logger.error(f'Error en cron_run_economic_activities: {str(e)}')

    def action_get_economic_activities(self):
        """
        Método original adaptado para manejo robusto de errores en cron
        """
        if not self.vat:
            return {'warning': {'title': 'Atención', 'message': _('Company VAT is invalid')}}

        try:
            # Importar el módulo API
            from ...electronic_invoice.models import api_facturae

            json_response = api_facturae.get_economic_activities(self)
            _logger.debug('E-INV CR - Economic Activities: %s', json_response)

            # Validar que json_response sea un diccionario
            if not isinstance(json_response, dict):
                _logger.error(f'Respuesta del API no es un diccionario: {type(json_response)}')
                return {'warning': {'title': 'Error', 'message': 'Respuesta del API inválida'}}

            # Verificar si hay un status válido
            if "status" not in json_response:
                _logger.error(f'Respuesta del API sin campo status: {json_response}')
                return {'warning': {'title': 'Error', 'message': 'Respuesta del API sin status'}}

            if json_response["status"] == 200:
                # Validar que existan las actividades
                if "activities" not in json_response:
                    _logger.error(f'Respuesta exitosa pero sin campo activities: {json_response}')
                    return {'warning': {'title': 'Error', 'message': 'Respuesta sin actividades'}}

                activities = json_response["activities"]

                # Validar que activities sea una lista
                if not isinstance(activities, list):
                    _logger.error(f'Activities no es una lista: {type(activities)}')
                    return {'warning': {'title': 'Error', 'message': 'Actividades en formato inválido'}}

                # Activity Codes
                a_codes = []
                for activity in activities:
                    if isinstance(activity, dict) and activity.get("estado") == "A":
                        code = activity.get("codigo")
                        if code:
                            a_codes.append(code)

                if a_codes:
                    economic_activities = self.env['economic.activity'].with_context(active_test=False).search(
                        [('code', 'in', a_codes)])
                    self.economic_activities_ids = economic_activities

                    if len(economic_activities) >= 1:
                        self.activity_id = economic_activities[0]

                # Actualizar nombre si está presente
                if "name" in json_response:
                    self.name = json_response["name"]

                # Actualizar estado de inscripción
                if "situacion" in json_response:
                    situacion = json_response['situacion']
                    self.inscribed = situacion in ['Inscrito', 'Inscrito de Oficio']

                return True  # Retorno exitoso para el cron
            else:
                # Manejar respuestas con status diferente a 200
                status = json_response.get("status", "Desconocido")
                message = json_response.get("text", f"Error {status}")

                alert = {
                    'title': str(status),
                    'message': message
                }
                return {'warning': alert}

        except ImportError as e:
            _logger.error(f'Error de importación: {str(e)}')
            return {'warning': {'title': 'Error', 'message': 'Módulo API no disponible'}}
        except Exception as e:
            _logger.error(f'Error en action_get_economic_activities: {str(e)}')
            return {'warning': {'title': 'Error', 'message': str(e)}}