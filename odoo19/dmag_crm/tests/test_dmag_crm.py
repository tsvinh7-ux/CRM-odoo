from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.dmag_crm.models.res_partner import normalize_vn_phone


@tagged('post_install', '-at_install')
class TestDmagCrm(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Segment = cls.env['dmag.segment']
        cls.pk1 = cls.env.ref('dmag_crm.segment_pk1')
        cls.pk3 = cls.env.ref('dmag_crm.segment_pk3')
        cls.team = cls.env.ref('dmag_crm.team_diagnosis')
        cls.clinic = cls.env['res.partner'].create({
            'name': 'Test Clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '0911 222 333',
        })

    def test_normalize_phone(self):
        self.assertEqual(normalize_vn_phone('84 965 265 828'), '0965265828')
        self.assertEqual(normalize_vn_phone('+84 965 265 828'), '0965265828')
        self.assertEqual(normalize_vn_phone('0973. 232.598'), '0973232598')
        self.assertEqual(normalize_vn_phone('352725111'), '0352725111')
        self.assertEqual(normalize_vn_phone('085 303 6666/0912595900'), '0853036666')

    def test_duplicate_clinic_phone_blocked(self):
        with self.assertRaises(ValidationError):
            self.env['res.partner'].create({
                'name': 'Same clinic', 'is_company': True, 'dmag_is_clinic': True, 'phone': '+84 911 222 333',
            })

    def test_segment_by_score_and_revenue(self):
        self.assertEqual(self.Segment._find_by_score(32), self.pk1)
        self.assertEqual(self.Segment._find_by_score(66), self.pk3)
        self.assertEqual(self.Segment._find_by_score(90).code, 'PK5')
        self.assertEqual(self.Segment._find_by_revenue(900), self.pk3)
        self.clinic.dmag_monthly_revenue = 900
        self.assertEqual(self.clinic.dmag_suggested_segment_id, self.pk3)
        self.clinic.action_dmag_apply_suggested_segment()
        self.assertEqual(self.clinic.dmag_segment_id, self.pk3)
        self.assertEqual(self.clinic.dmag_stage_g, 'g3')

    def test_stage_gate(self):
        lead = self.env['crm.lead'].create({
            'name': 'Gate test', 'type': 'opportunity', 'partner_id': self.clinic.id,
            'team_id': self.team.id, 'stage_id': self.env.ref('dmag_crm.stage_p1_new').id,
        })
        profile = self.env.ref('dmag_crm.stage_p1_profile')
        with self.assertRaises(UserError):
            lead.stage_id = profile
        lead.write({'dmag_disc': 'd', 'dmag_segment_id': self.pk3.id})
        lead.stage_id = profile
        self.assertEqual(lead.stage_id, profile)

    def test_capacity_warning_and_manual_approval(self):
        capacity = self.env['dmag.capacity']._for_date(False)
        self.assertTrue(capacity, 'Dữ liệu mặc định phải tạo chỉ tiêu cho quý hiện tại')
        capacity.slots_total = capacity.slots_used
        won = self.env.ref('dmag_crm.stage_p2_won')
        lead = self.env['crm.lead'].create({
            'name': 'Field deployment', 'type': 'opportunity', 'partner_id': self.clinic.id,
            'team_id': self.env.ref('dmag_crm.team_prescription').id, 'dmag_uses_capacity': True,
        })
        with self.assertRaises(UserError):
            lead.stage_id = won
        lead.dmag_capacity_approved_reason = 'Khách chiến lược'
        lead.action_dmag_approve_overcapacity()
        lead.stage_id = won
        self.assertEqual(lead.won_status, 'won')
        self.assertEqual(capacity.slots_left, -1)
