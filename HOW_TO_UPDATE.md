#!/usr/bin/env python3
"""
Demo script showing how to use the update_instructions.py utility
"""

print("=" * 80)
print("HOW TO UPDATE SPAM INSTRUCTIONS FOR EXISTING GROUPS")
print("=" * 80)

print("""
The buzz_buster bot stores spam detection instructions in the database for each group.
When you update the INSTRUCTIONS_DEFAULT_TEXT in your .env file, existing groups
won't automatically use the new instructions - they continue using what's stored
in their database records.

To apply new instructions to all existing groups:

1. First, update your .env file with the improved instructions:
   
   INSTRUCTIONS_DEFAULT_TEXT="Ты — антиспам-бот. Твоя задача — строго определить, является ли сообщение спамом. Спам — это любое сообщение, которое не относится к тематике группы и преследует скрытые цели (мошенничество, реклама, проституция). Ответ дай в формате JSON: {\\"result\\": true} если это спам, и {\\"result\\": false} если это не спам.\\n\\nСпамом считаются сообщения, обладающие одним или несколькими из следующих признаков:\\n\\n1.  **Бытовые услуги и разовая работа (\\"муж на час\\"):** Любые просьбы или предложения о выполнении простой работы за деньги, часто с личным подтекстом. Это включает в себя как прямые предложения, так и замаскированные просьбы о помощи.\\n    *Примеры:* 'ищу мужа на час, заплачу 5000', 'нужны люди перенести кирпичи', 'помогите убрать мусор, заплачу', 'починить кран, пишите в личку'.\\n\\n2.  **Навязчивые предложения контента:** Непрошеные предложения поделиться книгой, статьей, фильмом, VPN-сервисом или подкастом, особенно если автор сам инициировал разговор об этом в том же сообщении.\\n    *Примеры:* 'прочитал книгу... если интересно, могу скинуть', 'попробуй vpn_bot в телеграме'.\\n\\n3.  **Неуместные знакомства:** Прямые или завуалированные приглашения к личному общению, знакомству, прогулке, просмотру кино, не связанные с тематикой группы.\\n    *Примеры:* 'кто хочет прогуляться?', 'приглашу в гости для встречи', 'ищу с кем пообщаться'.\\n\\n4.  **Призывы к контакту:** Прямые или завуалированные приглашения написать в личные сообщения или конкретному пользователю ('пиши в лс', 'пиши @username').\\n\\n5.  **Финансы и Мошенничество:** Упоминание казино, криптовалют, ставок, а также обещания легких денег, \\"дать в долг\\" или \\"дать денег\\".\\n    *Примеры:* 'Занос с додепа...', 'дам денег', 'есть тема от 20к в день'.\\n\\n6.  **Подозрительное оформление:** Текст содержит слова с буквами из разных алфавитов (гомоглифы) или состоит **исключительно из эмодзи, знаков препинания или бессмысленного набора символов.**\\n\\n7.  **Реклама и набор:** Прямая реклама товаров/услуг, а также объявления о поиске или наборе людей куда-либо (на работу, в проект и т.д.).\\n    *Пример:* 'ищу партнеров в направление', 'открыт набор сотрудников'.\\n\\nПроанализируй сообщение ниже и дай свой вердикт."

2. Check what instructions are currently configured:
   
   python update_instructions.py --show

3. Update all groups with the new instructions:
   
   python update_instructions.py

4. Restart the bot to ensure the improved prompt engineering is active.

⚠️  IMPORTANT WARNINGS:
   - This will overwrite custom instructions for ALL groups
   - Groups that had specific customizations will lose them
   - Make sure your .env file has the complete instructions you want
   - Test the new instructions before applying to production groups

✅ BENEFITS:
   - All groups will use the improved prompt engineering
   - Significant reduction in false negatives expected
   - Consistent spam detection across all groups
   - Better handling of "harmless-looking" spam messages

The improved prompt structure includes:
   ✓ Expert role establishment
   ✓ Explicit strictness instructions  
   ✓ Clear warnings about "harmless" requests
   ✓ Structured analytical prompts
   ✓ Enhanced JSON response formatting
""")

print("=" * 80)