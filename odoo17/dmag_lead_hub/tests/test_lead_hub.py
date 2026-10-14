from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestLeadHub(TransactionCase):

    def test_lead_360_links_and_amounts(self):
        clinic = self.env['res.partner'].create({
            'name': 'Hub Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0944 333 222'})
        lead = self.env['crm.lead'].create({'name': 'Hub lead', 'type': 'opportunity', 'partner_id': clinic.id})
        product = self.env['product.template'].create({
            'name': 'Module field', 'type': 'service', 'list_price': 1000, 'taxes_id': [fields.Command.clear()],
            'invoice_policy': 'order', 'dmag_is_module': True, 'dmag_tier': 'field',
        }).product_variant_id
        order = self.env['sale.order'].create({
            'partner_id': clinic.id, 'opportunity_id': lead.id,
            'order_line': [fields.Command.create({'product_id': product.id})],
        })
        contract = self.env['dmag.contract'].browse(order.action_dmag_create_contract()['res_id'])
        contract.schedule_pattern = '50,50'
        contract.action_sign()
        first = contract.schedule_ids.sorted('sequence')[0]
        first.action_create_invoice()
        first.invoice_id.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=first.invoice_id.ids).create({})._create_payments()
        lead.invalidate_recordset()
        self.assertEqual(lead.dmag_contract_count, 1)
        self.assertEqual(lead.dmag_invoice_count, 1)
        self.assertEqual(lead.dmag_plan_count, 1, 'Đơn xác nhận khi ký hợp đồng → sinh lộ trình triển khai')
        self.assertEqual(lead.dmag_project_count, 1)
        self.assertEqual(lead.dmag_amount_ordered, 1000)
        self.assertEqual(lead.dmag_amount_paid, 500)
        self.assertEqual(lead.dmag_amount_due, 500)
        for action in (lead.action_dmag_view_contracts(), lead.action_dmag_view_invoices(),
                       lead.action_dmag_view_plans(), lead.action_dmag_view_projects()):
            self.assertTrue(action['domain'])
