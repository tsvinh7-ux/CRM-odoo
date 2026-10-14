from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .dmag_segment import DISC_SELECTION


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    dmag_pipeline_type = fields.Selection(related='team_id.dmag_pipeline_type',
                                          string='Pipeline DMAG')
    dmag_segment_id = fields.Many2one('dmag.segment', string='Phân khúc',
                                      compute='_compute_dmag_from_partner', store=True, readonly=False)
    dmag_stage_g = fields.Selection(related='partner_id.commercial_partner_id.dmag_stage_g', string='Chặng')
    dmag_dda_score = fields.Float(related='partner_id.commercial_partner_id.dmag_dda_score', string='Điểm DDA')
    dmag_t1_redflag = fields.Boolean(related='partner_id.commercial_partner_id.dmag_t1_redflag', string='Cờ đỏ T1')
    dmag_disc = fields.Selection(DISC_SELECTION, string='DISC người quyết định',
                                 compute='_compute_dmag_from_partner', store=True, readonly=False)
    dmag_fastcheck_score = fields.Integer('Fast-Check (số câu "Có"/7)')
    dmag_fastcheck_done = fields.Boolean('Đã làm Fast-Check')
    dmag_fastcheck_result = fields.Selection([
        ('solid', 'Nền tảng vững (6–7)'),
        ('restructure', 'Cần tái cấu trúc 90 ngày (4–5)'),
        ('risk', 'Rủi ro cao (< 4)'),
    ], string='Kết quả Fast-Check', compute='_compute_fastcheck_result', store=True)
    dmag_uses_capacity = fields.Boolean('Dùng suất triển khai thực địa',
                                        help='Khi thắng, cơ hội này chiếm 1 suất của quý.')
    dmag_capacity_approved_by = fields.Many2one('res.users', string='Duyệt vượt suất bởi', readonly=True, copy=False)
    dmag_capacity_approved_reason = fields.Char('Lý do duyệt vượt suất', copy=False)
    dmag_lead_owner_id = fields.Many2one('res.users', string='Người tạo/chăm lead',
                                         default=lambda self: self.env.user, domain=[('share', '=', False)],
                                         help='Dùng để chia hoa hồng phần "tạo/chăm lead".')

    @api.depends('partner_id')
    def _compute_dmag_from_partner(self):
        for lead in self:
            company = lead.partner_id.commercial_partner_id
            if company.dmag_segment_id:
                lead.dmag_segment_id = company.dmag_segment_id
            if lead.partner_id.dmag_disc:
                lead.dmag_disc = lead.partner_id.dmag_disc
            elif company.dmag_decision_disc:
                lead.dmag_disc = company.dmag_decision_disc

    @api.depends('dmag_fastcheck_done', 'dmag_fastcheck_score')
    def _compute_fastcheck_result(self):
        for lead in self:
            if not lead.dmag_fastcheck_done:
                lead.dmag_fastcheck_result = False
            elif lead.dmag_fastcheck_score >= 6:
                lead.dmag_fastcheck_result = 'solid'
            elif lead.dmag_fastcheck_score >= 4:
                lead.dmag_fastcheck_result = 'restructure'
            else:
                lead.dmag_fastcheck_result = 'risk'

    # ------------------------------------------------------------------
    # Cổng giai đoạn & suất quý
    # ------------------------------------------------------------------
    def _dmag_check_stage_gate(self, stage):
        missing_by_lead = []
        for lead in self:
            missing = [field.field_description for field in stage.dmag_required_field_ids
                       if field.name in lead._fields and not lead[field.name]]
            if missing:
                missing_by_lead.append(_('• %(lead)s: thiếu %(fields)s',
                                         lead=lead.display_name, fields=', '.join(missing)))
        if missing_by_lead:
            raise UserError(_('Chưa đủ điều kiện để chuyển sang giai đoạn "%(stage)s":\n%(details)s',
                              stage=stage.name, details='\n'.join(missing_by_lead)))

    def _dmag_check_capacity(self):
        leads = self.filtered(lambda lead: lead.dmag_uses_capacity and not lead.dmag_capacity_approved_by
                              and not lead.stage_id.is_won)
        if not leads:
            return
        capacity = self.env['dmag.capacity']._for_date(fields.Date.today())
        if not capacity:
            return
        capacity.invalidate_recordset(['slots_used', 'slots_left'])
        if capacity.slots_left < len(leads):
            raise UserError(_(
                'Quý %(period)s đã dùng %(used)s/%(total)s suất triển khai thực địa. '
                'Cần quản lý bấm "Duyệt vượt suất" trên cơ hội trước khi chốt.',
                period=capacity.name, used=capacity.slots_used, total=capacity.slots_total))

    def write(self, vals):
        if vals.get('stage_id') and not self.env.context.get('dmag_skip_gate'):
            stage = self.env['crm.stage'].browse(vals['stage_id'])
            moving = self.filtered(lambda lead: lead.stage_id != stage)
            if moving:
                if stage.dmag_required_field_ids:
                    moving._dmag_check_stage_gate(stage)
                if stage.is_won:
                    moving._dmag_check_capacity()
        return super().write(vals)

    def action_dmag_approve_overcapacity(self):
        if not self.env.user.has_group('dmag_crm.group_dmag_manager'):
            raise UserError(_('Chỉ quản lý DMAG được duyệt vượt suất.'))
        for lead in self:
            if not lead.dmag_capacity_approved_reason:
                raise UserError(_('Nhập "Lý do duyệt vượt suất" trước khi duyệt.'))
            lead.dmag_capacity_approved_by = self.env.user
            lead.message_post(body=_('Đã duyệt vượt suất quý. Lý do: %s', lead.dmag_capacity_approved_reason))
