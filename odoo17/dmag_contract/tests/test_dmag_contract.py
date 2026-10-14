from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDmagContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env['res.partner'].create({
            'name': 'Contract Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0933 222 111'})
        cls.product = cls.env['product.template'].create({
            'name': 'Setup module', 'type': 'service', 'list_price': 1000, 'taxes_id': [fields.Command.clear()],
            'invoice_policy': 'order', 'dmag_is_module': True, 'dmag_tier': 'field',
        }).product_variant_id
        cls.order = cls.env['sale.order'].create({
            'partner_id': cls.clinic.id,
            'order_line': [fields.Command.create({'product_id': cls.product.id, 'product_uom_qty': 3})],
        })

    def _contract(self, pattern='40,40,20'):
        contract = self.env['dmag.contract'].browse(self.order.action_dmag_create_contract()['res_id'])
        contract.schedule_pattern = pattern
        return contract

    def test_schedule_and_installment_invoices(self):
        contract = self._contract()
        contract.action_generate_schedule()
        self.assertEqual(contract.schedule_ids.mapped('percent'), [40, 40, 20])
        self.assertEqual(contract.schedule_ids.mapped('amount'), [1200, 1200, 600])
        with self.assertRaises(UserError):
            contract.schedule_ids[0].action_create_invoice()  # chưa ký
        contract.action_sign()
        self.assertEqual(self.order.state, 'sale', 'Ký hợp đồng thì xác nhận đơn bán')
        first, second, last = contract.schedule_ids.sorted('sequence')
        first.action_create_invoice()
        invoice = first.invoice_id
        self.assertEqual(invoice.amount_total, 1200)
        self.assertEqual(invoice.invoice_line_ids.product_id, self.product, 'Giữ sản phẩm gốc để tính hoa hồng')
        invoice.action_post()
        self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({})._create_payments()
        self.assertEqual(first.state, 'paid')
        self.assertEqual(contract.amount_paid, 1200)
        self.assertEqual(contract.amount_due, 1800)
        self.assertAlmostEqual(contract.paid_percent, 40)
        second.action_create_invoice()
        last.action_create_invoice()
        self.assertAlmostEqual(sum(contract.schedule_ids.invoice_id.mapped('amount_total')), 3000)
        self.assertEqual(self.order.order_line.qty_invoiced, 3)

    def test_overdue_and_reminders(self):
        contract = self._contract('50,50')
        contract.date_start = fields.Date.today() - timedelta(days=40)
        contract.action_generate_schedule()
        contract.action_sign()
        first = contract.schedule_ids.sorted('sequence')[0]
        first.action_create_invoice()
        first.invoice_id.action_post()
        self.assertEqual(first.state, 'overdue')
        self.assertEqual(contract.amount_overdue, 1500)
        self.env['dmag.contract']._cron_payment_reminders()
        summaries = contract.activity_ids.mapped('summary')
        self.assertTrue(any('quá hạn' in s for s in summaries))
        self.assertTrue(any('Xuất hoá đơn' in s for s in summaries))

    def test_pattern_must_total_100(self):
        contract = self._contract('40,40')
        with self.assertRaises(ValidationError):
            contract.action_generate_schedule()
