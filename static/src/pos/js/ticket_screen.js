/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { AlertDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { TicketScreen } from "@point_of_sale/app/screens/ticket_screen/ticket_screen";

patch(TicketScreen.prototype, {
    ticofacDocumentType(order) {
        const types = {
            FE: _t("Factura electrónica"),
            TE: _t("Tiquete electrónico"),
            NC: _t("Nota de crédito"),
        };
        return types[order?.raw?.tipo_documento] || order?.raw?.tipo_documento || "-";
    },
    ticofacInvoiceNumber(order) {
        return order?.raw?.ticofac_invoice_name || order?.raw?.sequence || "-";
    },
    ticofacRejectionReason(order) {
        return order?.raw?.ticofac_rejection_reason || "";
    },
    ticofacRejectionSummary(order) {
        return order?.raw?.ticofac_rejection_summary || _t("Hacienda rechazó el documento. Revise los datos y vuelva a intentarlo.");
    },
    ticofacShowRejectionReason(order) {
        this.dialog.add(AlertDialog, {
            title: _t("Motivo del rechazo de Hacienda"),
            contentClass: "ticofac-rejection-dialog",
            body: this.ticofacRejectionSummary(order),
        });
    },
    ticofacInvoiceState(order) {
        const states = {
            aceptado: _t("Aceptada"),
            rechazado: _t("Rechazada"),
            recibido: _t("Recibida"),
            firma_invalida: _t("Firma inválida"),
            error: _t("Error"),
            procesando: _t("Procesando"),
            na: _t("No aplica"),
            ne: _t("No encontrada"),
        };
        return states[order?.raw?.ticofac_invoice_state] || _t("Pendiente");
    },
    ticofacInvoiceStateClass(order) {
        const state = order?.raw?.ticofac_invoice_state || "pendiente";
        if (["rechazado", "firma_invalida", "error"].includes(state)) {
            return "o_ticofac_status o_ticofac_status--danger";
        }
        if (state === "aceptado") {
            return "o_ticofac_status o_ticofac_status--success";
        }
        if (["recibido", "ne"].includes(state)) {
            return "o_ticofac_status o_ticofac_status--info";
        }
        if (state === "na") {
            return "o_ticofac_status o_ticofac_status--muted";
        }
        return "o_ticofac_status o_ticofac_status--warning";
    },
    ticofacInvoiceStateIcon(order) {
        const state = order?.raw?.ticofac_invoice_state;
        if (state === "aceptado") return "fa-check-circle";
        if (["rechazado", "firma_invalida", "error"].includes(state)) return "fa-times-circle";
        if (["recibido", "ne"].includes(state)) return "fa-info-circle";
        if (state === "na") return "fa-minus-circle";
        return "fa-clock-o";
    },
    async ticofacResendInvoiceEmail(order) {
        try {
            const result = await this.pos.data.call(
                "pos.order",
                "ticofac_resend_invoice_email",
                [[order.id]]
            );
            this.env.services.notification.add(
                _t("Factura %s reenviada a %s", result.invoice_name, result.email),
                { type: "success" }
            );
        } catch (error) {
            this.dialog.add(AlertDialog, {
                title: _t("No fue posible reenviar la factura"),
                body: error?.data?.message || error?.message || _t("Error inesperado"),
            });
        }
    },
});
