from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDmagCommission(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.closer = Users.create({'name': 'Closer', 'login': 'closer@dmag.test'})
        cls.hunter = Users.create({'name': 'Hunter', 'login': 'hunter@dmag.test'})
        cls.owner = Users.create({'name': 'Owner', 'login': 'owner@dmag.test'})
        cls.plan = cls.env['dmag.commission.plan'].create({
            'name': 'Test plan',
            'line_ids': [fields.Command.create({'commission_group': 'module_field', 'rate': 5}),
                         fields.Command.create({'commission_group': 'dda_deposit', 'rate': 10})],
        })
        cls.today = fields.Date.today()
        for user, target in ((cls.closer, 100000), (cls.hunter, 0)):
            cls.env['dmag.commission.assignment'].create({
                'user_id': user.id, 'plan_id': cls.plan.id, 'date_from': cls.today.replace(day=1),
                'monthly_target': target, 'state': 'approved',
            })
        cls.clinic = cls.env['res.partner'].create({
            'name': 'Commission Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0966 555 444',
            'dmag_account_owner_id': cls.owner.id,
        })
        cls.product = cls.env['product.template'].create({
            'name': 'Field module', 'type': 'service', 'list_price': 120000, 'taxes_id': [fields.Command.clear()],
            'dmag_is_module': True, 'dmag_tier': 'field', 'invoice_policy': 'order',
        }).product_variant_id
        cls.lead = cls.env['crm.lead'].create({
            'name': 'Commission lead', 'type': 'opportunity', 'partner_id': cls.clinic.id,
            'dmag_lead_owner_id': cls.hunter.id,
        })

    def _invoice(self):
        order = self.env['sale.order'].create({
            'partner_id': self.clinic.id, 'user_id': self.closer.id, 'opportunity_id': self.lead.id,
            'order_line': [fields.Command.create({'product_id': self.product.id})],
        })
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.action_post()
        return invoice

    def _pay(self, invoice, amount):
        return self.env['account.payment.register'].with_context(
            active_model='account.move', active_ids=invoice.ids).create({'amount': amount})._create_payments()

    def _lines(self, invoice):
        return self.env['dmag.commission.line'].search([('invoice_id', '=', invoice.id)])

    def test_group_from_tier(self):
        self.assertEqual(self.product.product_tmpl_id.dmag_commission_group, 'module_field')

    def test_no_commission_before_payment(self):
        invoice = self._invoice()
        self.assertFalse(self._lines(invoice), 'Chưa thu tiền thì chưa có hoa hồng')

    def test_commission_on_partial_payment(self):
        invoice = self._invoice()
        self._pay(invoice, 60000)  # thu 50%
        lines = self._lines(invoice)
        by_role = {(l.user_id, l.role): l for l in lines}
        closer_line = by_role[(self.closer, 'closer')]
        self.assertAlmostEqual(closer_line.base_amount, 60000)
        self.assertAlmostEqual(closer_line.amount, 60000 * 0.70 * 0.05)
        hunter_line = by_role[(self.hunter, 'lead')]
        self.assertAlmostEqual(hunter_line.amount, 60000 * 0.20 * 0.05)
        # Account Owner chưa được gán chính sách → không có dòng
        self.assertNotIn(self.owner, lines.user_id)

    def test_clawback_on_unreconcile(self):
        invoice = self._invoice()
        payment = self._pay(invoice, 120000)
        total = sum(self._lines(invoice).mapped('amount'))
        self.assertGreater(total, 0)
        payment.move_id.line_ids.remove_move_reconcile()
        lines = self._lines(invoice)
        self.assertTrue(any(lines.mapped('is_clawback')))
        self.assertAlmostEqual(sum(lines.mapped('amount')), 0.0)

    def test_monthly_statement_multiplier(self):
        invoice = self._invoice()
        self._pay(invoice, 120000)
        statements = self.env['dmag.commission.statement']._generate_for_month(self.today)
        statement = statements.filtered(lambda s: s.user_id == self.closer)
        self.assertEqual(statement.collected, 120000)
        self.assertEqual(statement.target, 100000)
        base = 120000 * 0.70 * 0.05
        self.assertAlmostEqual(statement.commission_base, base)
        # Vượt 20% mục tiêu: phần vượt (20.000/120.000) được × 1,2
        expected = base + base * (20000 / 120000) * 0.2
        self.assertAlmostEqual(statement.commission_total, expected)
        statement.action_confirm()
        statement.action_approve()
        self.assertEqual(statement.payroll_month.month, (self.today.month % 12) + 1)
        statement.action_push_payroll()
        self.assertEqual(statement.state, 'payroll')
        self.assertEqual(statement._dmag_payroll_input_vals()['code'], 'HOA_HONG')

    def test_low_achievement_multiplier(self):
        total, multiplier = self.plan._apply_multiplier(1000, collected=50, target=100)
        self.assertEqual((total, multiplier), (800, 0.8))
        total, multiplier = self.plan._apply_multiplier(1000, collected=90, target=100)
        self.assertEqual((total, multiplier), (1000, 1.0))
