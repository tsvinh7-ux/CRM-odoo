from datetime import timedelta

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDmagDelivery(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.clinic = cls.env['res.partner'].create({
            'name': 'Delivery Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0977 111 000',
            'dmag_account_owner_id': cls.env.user.id,
        })
        cls.owner = cls.env['res.partner'].create({'name': 'Owner', 'parent_id': cls.clinic.id})
        cls.channel = cls.env['slide.channel'].create({'name': 'Test course', 'channel_type': 'training'})
        pillar = cls.env.ref('dmag_dda.pillar_t8')

        def module(tier, **extra):
            return cls.env['product.template'].create(dict({
                'name': f'Module {tier}', 'type': 'service', 'list_price': 1000000,
                'dmag_is_module': True, 'dmag_pillar_id': pillar.id, 'dmag_tier': tier,
            }, **extra)).product_variant_id

        cls.p_self = module('self', dmag_channel_id=cls.channel.id)
        cls.p_one = module('one_on_one', dmag_session_count=2)
        cls.p_field = module('field', dmag_sprint_count=3)

    def _confirm_order(self, products):
        order = self.env['sale.order'].create({
            'partner_id': self.clinic.id,
            'order_line': [fields.Command.create({'product_id': p.id}) for p in products],
        })
        order.action_confirm()
        return order

    def test_plan_created_on_confirm(self):
        order = self._confirm_order(self.p_self | self.p_one | self.p_field)
        plan = order.dmag_delivery_plan_ids
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan.date_day90, plan.date_start + timedelta(days=90))
        self.assertEqual(self.clinic.dmag_lifecycle, 'active')
        by_tier = {line.tier: line for line in plan.line_ids}
        self.assertEqual(set(by_tier), {'self', 'one_on_one', 'field'})
        # Tự học: ghi danh người liên hệ vào khoá eLearning
        self.assertIn(self.owner, self.channel.sudo().channel_partner_ids.partner_id)
        # Kèm 1:1: số buổi theo sản phẩm
        self.assertEqual(by_tier['one_on_one'].sessions_total, 2)
        # Thực địa: dự án có kickoff + 3 Sprint
        project = by_tier['field'].project_id
        self.assertEqual(len(project.task_ids), 4)
        self.assertEqual(project.partner_id, self.clinic)

    def test_progress_and_pulse(self):
        order = self._confirm_order(self.p_one)
        plan = order.dmag_delivery_plan_ids
        line = plan.line_ids
        session = self.env['dmag.delivery.session'].create({'line_id': line.id, 'name': 'Buổi 1'})
        self.assertTrue(session.calendar_event_id, 'Buổi hẹn phải tạo lịch')
        session.action_done()
        self.assertEqual(line.progress, 50)
        plan._update_pulse()
        self.assertEqual(plan.pulse, 'green')
        # Trễ hạn > 7 ngày → Đỏ và giao việc cho người phụ trách
        line.date_deadline = fields.Date.today() - timedelta(days=10)
        plan._update_pulse()
        self.assertEqual(plan.pulse, 'red')
        self.assertTrue(plan.activity_ids)
        # Trễ 3 ngày → Vàng
        line.date_deadline = fields.Date.today() - timedelta(days=3)
        plan._update_pulse()
        self.assertEqual(plan.pulse, 'yellow')

    def test_silence_turns_red(self):
        plan = self._confirm_order(self.p_one).dmag_delivery_plan_ids
        today = fields.Date.today() + timedelta(days=25)
        pulse, reasons = plan._evaluate_pulse(today)
        self.assertEqual(pulse, 'red')
        self.assertTrue(any('check-in' in r for r in reasons))

    def test_reaudit_reminder_and_creation(self):
        plan = self._confirm_order(self.p_field).dmag_delivery_plan_ids
        plan._remind_reaudit(today=plan.date_day90 - timedelta(days=3))
        self.assertTrue(plan.reaudit_reminded)
        plan.action_create_reaudit()
        self.assertTrue(plan.reaudit_id.is_reaudit)
        self.assertEqual(len(plan.reaudit_id.line_ids), 10)
