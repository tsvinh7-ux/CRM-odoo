from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dmag_dda.models.dmag_prescription import suggest_tier


@tagged('post_install', '-at_install')
class TestDmagDda(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pk1 = cls.env.ref('dmag_crm.segment_pk1')
        cls.pk3 = cls.env.ref('dmag_crm.segment_pk3')
        cls.t1 = cls.env.ref('dmag_dda.pillar_t1')
        cls.t8 = cls.env.ref('dmag_dda.pillar_t8')
        tiers = ['self', 'guided', 'one_on_one', 'field']
        cls.env['product.template'].create([{
            'name': f'Test module {code} {tier}', 'type': 'service', 'list_price': 1000000 * (i + 1),
            'dmag_is_module': True, 'dmag_module_code': f'TEST-{code}',
            'dmag_pillar_id': cls.env.ref(f'dmag_dda.pillar_{code.lower()}').id, 'dmag_tier': tier,
        } for code in ('T1', 'T3', 'T8', 'T9') for i, tier in enumerate(tiers)])
        cls.clinic = cls.env['res.partner'].create({
            'name': 'DDA Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0988 777 666',
        })

    def _audit(self, genba, self_scores=None):
        audit = self.env['dmag.dda.audit'].create({'partner_id': self.clinic.id, 'state': 'onsite'})
        self.assertEqual(len(audit.line_ids), 10, 'Hồ sơ mới phải có sẵn 10 trụ cột')
        self.env['dmag.dda.audit']._dmag_demo_fill(audit.ids, self_scores or genba, genba)
        return audit

    def test_suggest_tier_rules(self):
        self.assertEqual(suggest_tier(0.5, self.t8, self.pk3), 'self')
        self.assertEqual(suggest_tier(2.5, self.t8, self.pk3), 'guided')
        self.assertEqual(suggest_tier(4.5, self.t8, self.pk3), 'one_on_one')
        self.assertEqual(suggest_tier(6, self.t8, self.pk3), 'field')
        self.assertEqual(suggest_tier(2, self.t1, self.pk3), 'field')
        # PK1 không bán kèm 1:1 / thực địa → kẹp về "có hướng dẫn"
        self.assertEqual(suggest_tier(6, self.t8, self.pk1), 'guided')
        self.assertFalse(suggest_tier(0, self.t8, self.pk3))

    def test_audit_approval_updates_clinic(self):
        audit = self._audit([10, 7, 4, 6, 6, 7, 6, 3.5, 1.5, 6], [10, 7, 6, 7, 8, 7.5, 7, 6, 5, 7])
        self.assertEqual(audit.total_genba, 57)
        self.assertEqual(audit.total_self, 70.5)
        self.assertEqual(audit.segment_id, self.pk3)
        self.assertFalse(audit.t1_redflag)
        self.assertIn('<svg', audit.radar_svg)
        audit.action_submit_review()
        audit.action_approve()
        self.assertEqual(self.clinic.dmag_dda_score, 57)
        self.assertEqual(self.clinic.dmag_segment_id, self.pk3)
        self.assertEqual(self.clinic.dmag_stage_g, 'g3')
        self.assertEqual(self.clinic.dmag_lifecycle, 'diagnosed')

    def test_submit_requires_all_pillars(self):
        audit = self.env['dmag.dda.audit'].create({'partner_id': self.clinic.id, 'state': 'onsite'})
        with self.assertRaises(UserError):
            audit.action_submit_review()

    def test_t1_redflag_restricts_prescription(self):
        audit = self._audit([6, 3, 2.5, 3, 4, 3.5, 3, 2.5, 1.5, 3])
        self.assertTrue(audit.t1_redflag)
        self.assertEqual(audit.flow, 1)
        audit.action_submit_review()
        audit.action_approve()
        self.assertTrue(self.clinic.dmag_t1_redflag)
        self.assertEqual(self.clinic.dmag_segment_id, self.pk1)
        action = audit.action_create_prescription()
        prescription = self.env['dmag.prescription'].browse(action['res_id'])
        self.assertEqual(prescription.line_ids[0].pillar_id, self.t1, 'T1 phải đứng đầu đơn kê')
        # PK1 + cờ đỏ: các trụ cột khác bị chặn khi duyệt
        with self.assertRaises(UserError):
            prescription.action_confirm()
        prescription.line_ids.filtered(lambda l: not l.pillar_id.is_knockout).unlink()
        prescription.line_ids.tier = 'guided'
        prescription.line_ids._onchange_tier()
        prescription.action_confirm()
        self.assertEqual(prescription.state, 'confirmed')

    def test_prescription_to_quotation(self):
        audit = self._audit([10, 7, 4, 6, 6, 7, 6, 3.5, 1.5, 6])
        audit.action_submit_review()
        audit.action_approve()
        lead = self.env['crm.lead'].create({
            'name': 'P2', 'type': 'opportunity', 'partner_id': self.clinic.id,
            'team_id': self.env.ref('dmag_crm.team_prescription').id,
        })
        prescription = self.env['dmag.prescription'].browse(audit.action_create_prescription()['res_id'])
        prescription.lead_id = lead
        tiers = {line.pillar_id.code: line.tier for line in prescription.line_ids}
        self.assertEqual(tiers['T9'], 'field')       # khoảng thiếu 6.5
        self.assertEqual(tiers['T8'], 'one_on_one')  # khoảng thiếu 3.5
        self.assertEqual(tiers['T3'], 'one_on_one')  # khoảng thiếu 4
        self.assertEqual(prescription.line_ids[0].pillar_id.code, 'T3', 'Nền móng T3 đứng trước')
        # Chỉ giữ các trụ cột có module trong danh mục minh hoạ
        prescription.line_ids.filtered(lambda l: not l.product_id).unlink()
        prescription.action_confirm()
        self.assertTrue(lead.dmag_prescription_ready)
        prescription.action_create_quotation()
        order = prescription.sale_order_id
        self.assertEqual(order.opportunity_id, lead)
        self.assertEqual(len(order.order_line), len(prescription.line_ids))
        self.assertTrue(lead.dmag_uses_capacity, 'Có dòng thực địa → cơ hội dùng suất quý')

    def test_stage_gate_requires_deposit(self):
        lead = self.env['crm.lead'].create({
            'name': 'Deposit gate', 'type': 'opportunity', 'partner_id': self.clinic.id,
            'team_id': self.env.ref('dmag_crm.team_diagnosis').id,
        })
        with self.assertRaises(UserError):
            lead.stage_id = self.env.ref('dmag_crm.stage_p1_paid')
        lead.dmag_dda_paid_manual = True
        lead.stage_id = self.env.ref('dmag_crm.stage_p1_paid')
        self.assertTrue(lead.dmag_dda_paid)
