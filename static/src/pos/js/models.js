/** @odoo-module **/

import { PosOrder } from "@point_of_sale/app/models/pos_order";
import { patch } from "@web/core/utils/patch";

// WeakMap storage - completely outside Odoo's proxy
const _orderData = new WeakMap();

function getOrderData(order) {
    if (!_orderData.has(order)) {
        _orderData.set(order, {
            tipo_documento: null,
            number_electronic: null,
            sequence: null,
            journal_id: null,
            refund_reason: null,
            refund_reference_code_id: null,
        });
    }
    return _orderData.get(order);
}

patch(PosOrder.prototype, {
    setup(vals) {
        super.setup(...arguments);
        const data = getOrderData(this);
        data.tipo_documento = vals.tipo_documento || null;
        data.number_electronic = vals.number_electronic || null;
        data.sequence = vals.sequence || null;
        data.journal_id = vals.journal_id || null;
        data.refund_reason = vals.refund_reason || null;
        data.refund_reference_code_id = vals.refund_reference_code_id || null;
    },

    set_tipo_documento(tipoDoc) {
        getOrderData(this).tipo_documento = tipoDoc;
        console.log("✅ Se generó el documento:", tipoDoc);
    },
    get_tipo_documento() {
        return getOrderData(this).tipo_documento;
    },

    set_number_electronic(number) {
        getOrderData(this).number_electronic = number;
        console.log("✅ Se generó la clave:", number);
    },
    get_number_electronic() {
        return getOrderData(this).number_electronic;
    },

    set_sequence(number) {
        getOrderData(this).sequence = number;
        console.log("✅ Se generó la secuencia:", number);
    },
    get_sequence() {
        return getOrderData(this).sequence;
    },

    set_journal_id(number) {
        getOrderData(this).journal_id = number;
    },
    get_journal_id() {
        return getOrderData(this).journal_id;
    },

    set_reason_refund(reason) {
        getOrderData(this).refund_reason = reason;
    },
    get_reason_refund() {
        return getOrderData(this).refund_reason;
    },
    
    set_refund_reference_code_id(id) {
        getOrderData(this).refund_reference_code_id = id;
    },
    get_refund_reference_code_id() {
        return getOrderData(this).refund_reference_code_id;
    },

    serialize(options) {
        const json = super.serialize(...arguments);
        const data = getOrderData(this);
        
        json.tipo_documento = data.tipo_documento;
        json.number_electronic = data.number_electronic;
        json.sequence = data.sequence;
        json.journal_id = data.journal_id;
        json.refund_reason = data.refund_reason;
        json.refund_reference_code_id = data.refund_reference_code_id;
        
        return json;
    },

    export_for_printing() {
        const json = super.export_for_printing(...arguments);
        const numberElectronic = this.get_number_electronic() || this.number_electronic;
        json.headerData.number_electronic = numberElectronic;
        json.headerData.sequence =
            this.get_sequence() || this.sequence || numberElectronic?.substring(21, 41);
        json.headerData.tipo_documento = this.get_tipo_documento() || this.tipo_documento;
        json.headerData.partner = this.get_partner() || false;
        json.headerData.ticofac_receipt_enabled = this.config.ticofac_receipt_enabled;
        json.headerData.ticofac_receipt_show_customer = this.config.ticofac_receipt_show_customer;
        json.headerData.ticofac_receipt_show_address = this.config.ticofac_receipt_show_address;
        json.headerData.ticofac_receipt_show_activity = this.config.ticofac_receipt_show_activity;
        json.headerData.order_date = json.date;
        json.headerData.terminal = this.config.name;
        json.headerData.is_restaurant = this.config.module_pos_restaurant === true;
        json.headerData.economic_activity =
            this.company.activity_id?.code || this.company.activity_id?.name || false;
        json.fiscal_sale_condition = "Contado";
        json.currency_name = this.currency?.name || "CRC";
        json.fiscal_show_payment = this.config.ticofac_receipt_show_payment;
        json.fiscal_qr_label = this.config.ticofac_receipt_qr_label || "";
        json.fiscal_qr_size_cm =
            ({ small: "2.4cm", medium: "3cm", large: "3.6cm" })[
                this.config.ticofac_receipt_qr_size
            ] || "3.6cm";
        json.fiscal_legal_text = this.config.ticofac_receipt_legal_text || "";
        json.fiscal_document_version = "4.4";
        json.fiscal_qr_code =
            this.config.ticofac_receipt_enabled &&
            this.config.ticofac_receipt_show_qr &&
            numberElectronic
                ? `/ticofac/pos/qr/${encodeURIComponent(numberElectronic)}`
                : false;
        return json;
    },
});
