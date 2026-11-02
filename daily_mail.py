"""邮件附件领取，沿用官方客户端 MailProxy 的请求结构。"""
import time


def mail_list(flow):
    response = flow.request('scene.mailHandler.getAllMail', {}, timeout=15)
    if response.get('code') != 200 or response.get('error'):
        raise RuntimeError(response.get('error', '邮件列表读取失败'))
    rows = response.get('mails')
    if not isinstance(rows, list):
        raise RuntimeError('邮件列表格式不符合客户端定义，已停止领取')
    return rows


def has_attachment(mail):
    # status只表示已读/未读，不能用于判断附件是否已领取。
    return bool(mail.get('subType')) and bool(mail.get('id'))


def claim_mail_rewards(flow, log):
    rows = mail_list(flow)
    pending = [mail for mail in rows if has_attachment(mail)]
    log('  共%d封邮件，其中%d封带附件；纯文字邮件保留。' % (len(rows), len(pending)))
    completed = []
    seen = set()
    for mail in pending:
        mail_id = str(mail['id'])
        if mail_id in seen:
            continue
        seen.add(mail_id)
        response = flow.request('scene.mailHandler.getAndRemoveMail', {'mailId': mail['id']}, timeout=15)
        if response.get('code') != 200 or response.get('error'):
            raise RuntimeError('邮件“%s”领取失败：%s；停止后续邮件领取' % (mail.get('title', mail_id), response.get('error', response)))
        if 'items' not in response:
            raise RuntimeError('邮件“%s”返回成功但没有附件字段，需核实，停止后续领取' % mail.get('title', mail_id))
        completed.append(mail_id)
        log('  邮件“%s”领取回包成功：%s' % (mail.get('title', mail_id), response['items']))
        time.sleep(.3)
    remaining = mail_list(flow)
    remaining_ids = {str(mail.get('id')) for mail in remaining}
    unconfirmed = [mail_id for mail_id in completed if mail_id in remaining_ids]
    if unconfirmed:
        raise RuntimeError('领取后仍存在%d封已处理邮件，需核实' % len(unconfirmed))
    log('  邮件处理完成：%d封领取回包成功，刷新确认已从邮件列表移除。' % len(completed))
    return len(completed)
