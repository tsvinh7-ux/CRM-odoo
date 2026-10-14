from odoo import fields, models


class DmagChannelReply(models.TransientModel):
    _name = 'dmag.channel.reply'
    _description = 'Trả lời khách qua Facebook/Zalo'

    conversation_id = fields.Many2one('dmag.conversation', string='Hội thoại', required=True)
    lead_id = fields.Many2one('crm.lead')
    channel = fields.Selection(related='conversation_id.channel')
    can_reply = fields.Boolean(related='conversation_id.can_reply')
    reply_deadline = fields.Datetime(related='conversation_id.reply_deadline')
    history = fields.One2many(related='conversation_id.message_line_ids', string='Lịch sử')
    body = fields.Text('Tin nhắn', required=True)

    def action_send(self):
        self.conversation_id._dmag_send_text(self.body)
        return {'type': 'ir.actions.act_window_close'}
