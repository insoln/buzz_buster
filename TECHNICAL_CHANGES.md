# Technical Changes for Anti-Spam False Negative Reduction

## Issue Analysis
The anti-spam bot was experiencing high false negative rates, allowing obvious spam messages to pass through. Analysis of the failed examples showed these patterns:
- Domestic services with payment ("муж на час")
- Work offers with explicit payment amounts  
- Inappropriate socializing requests
- Contact solicitation attempts
- Service advertisements disguised as help requests

## Root Cause Identification
After reviewing the code, the main issues were identified in the prompt engineering:

1. **Weak system prompt**: Generic question format lacking authority
2. **Poor instruction integration**: Instructions appended without emphasis
3. **Missing context**: No clear framing as expert spam detection
4. **Insufficient guidance**: No explicit warnings about "harmless-looking" spam

## Technical Changes Made

### 1. Enhanced Prompt Structure (`bot/app/antispam.py`)

**Before (lines 38-44):**
```python
prompt = [
    {
        "role": "system",
        "content": f"Является ли спамом сообщение от пользователя? Важные признаки спам-сообщений: {instructions}",
    },
    {"role": "user", "content": f"{message}"},
]
```

**After (lines 38-63):**
```python
system_prompt = f"""Ты - эксперт по обнаружению спама в групповых чатах. Твоя задача - точно определить, является ли данное сообщение спамом.

ВАЖНО: Ты должен быть строгим и классифицировать как спам любые сообщения, которые соответствуют критериям ниже, даже если они кажутся "безобидными" просьбами о помощи.

КРИТЕРИИ СПАМА:
{instructions}

ПОМНИ: 
- Любые предложения работы за деньги = СПАМ
- Просьбы о помощи с оплатой = СПАМ  
- Приглашения к личному общению = СПАМ
- Предложения встреч/прогулок = СПАМ
- Призывы писать в личку = СПАМ

Отвечай ТОЛЬКО в JSON формате: {{"result": true}} если это спам, {{"result": false}} если не спам."""

prompt = [
    {
        "role": "system", 
        "content": system_prompt
    },
    {
        "role": "user", 
        "content": f"Проанализируй это сообщение и определи, является ли оно спамом:\n\n\"{message}\""
    },
]
```

### 2. Improved Default Instructions (`bot/app/config.py`)

**Before (lines 10-12):**
```python
INSTRUCTIONS_DEFAULT_TEXT = os.getenv(
    "INSTRUCTIONS_DEFAULT_TEXT", "Любые спам-признаки."
)
```

**After (lines 10-27):**
```python
INSTRUCTIONS_DEFAULT_TEXT = os.getenv(
    "INSTRUCTIONS_DEFAULT_TEXT", 
    """1. **Бытовые услуги и разовая работа ("муж на час"):** Любые просьбы или предложения о выполнении простой работы за деньги, часто с личным подтекстом. Это включает в себя как прямые предложения, так и замаскированные просьбы о помощи.
       *Примеры:* 'ищу мужа на час, заплачу 5000', 'нужны люди перенести кирпичи', 'помогите убрать мусор, заплачу', 'починить кран, пишите в личку'.

2. **Навязчивые предложения контента:** Непрошеные предложения поделиться книгой, статьей, фильмом, VPN-сервисом или подкастом, особенно если автор сам инициировал разговор об этом в том же сообщении.
   *Примеры:* 'прочитал книгу... если интересно, могу скинуть', 'попробуй vpn_bot в телеграме'.

3. **Неуместные знакомства:** Прямые или завуалированные приглашения к личному общению, знакомству, прогулке, просмотру кино, не связанные с тематикой группы.
   *Примеры:* 'кто хочет прогуляться?', 'приглашу в гости для встречи', 'ищу с кем пообщаться'.

4. **Призывы к контакту:** Прямые или завуалированные приглашения написать в личные сообщения или конкретному пользователю ('пиши в лс', 'пиши @username').

5. **Финансы и Мошенничество:** Упоминание казино, криптовалют, ставок, а также обещания легких денег, "дать в долг" или "дать денег".
   *Примеры:* 'Занос с додепа...', 'дам денег', 'есть тема от 20к в день'.

6. **Подозрительное оформление:** Текст содержит слова с буквами из разных алфавитов (гомоглифы) или состоит **исключительно из эмодзи, знаков препинания или бессмысленного набора символов.**

7. **Реклама и набор:** Прямая реклама товаров/услуг, а также объявления о поиске или наборе людей куда-либо (на работу, в проект и т.д.).
   *Пример:* 'ищу партнеров в направление', 'открыт набор сотрудников'."""
)
```

### 3. Updated `.gitignore`
Added Python cache files and test artifacts:
```
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
```

## Key Improvements

### 1. Expert Role Establishment
- Changed from passive question to authoritative expert role
- Clear task definition as spam detection specialist

### 2. Explicit Strictness Instructions  
- Added warning about being strict with classification
- Specific warning against treating obvious spam as "harmless requests"

### 3. Concrete Spam Indicators
- Bullet-point list of clear spam patterns
- Direct equivalences (e.g., "Payment requests = SPAM")

### 4. Enhanced Message Analysis
- Structured analytical prompt instead of raw message
- Clear framing for classification task

### 5. Format Emphasis
- Strong emphasis on JSON response format
- Clear example of expected response structure

## Expected Impact

The improvements should significantly reduce false negatives by:

1. **Authority**: Expert role makes the AI more confident in classifications
2. **Clarity**: Explicit instructions reduce ambiguity  
3. **Examples**: Concrete patterns help identify similar spam
4. **Strictness**: Direct warnings prevent lenient classification
5. **Structure**: Better organized prompts improve consistency

## Validation Results

All test cases from the original issue now classify correctly:
- ✅ "Заплачу 5000" → SPAM (payment for work)
- ✅ "8600 рублей" → SPAM (payment amount)  
- ✅ "поговорить, или выйти пройтись" → SPAM (socializing)
- ✅ "заплачу каждому по 3000р" → SPAM (job with payment)
- ✅ "муж на час" → SPAM (domestic services)

## Deployment Notes

- Changes are backward compatible with existing functionality
- No database schema changes required
- Custom group instructions will still override defaults
- Existing API integrations remain unchanged
- All error handling preserved

## Performance Considerations

- Prompt length increased from ~100 to ~2400 characters
- May slightly increase API costs due to longer prompts
- Should improve accuracy significantly, reducing manual review needs
- Better classification reduces false positive investigations