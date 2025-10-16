#!/usr/bin/env python3
"""
Demonstration of the anti-spam improvements
Shows the before/after prompt structure and expected behavior
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'bot'))

def show_old_vs_new_prompt():
    """Compare the old and new prompt structures"""
    
    print("=" * 80)
    print("ANTI-SPAM PROMPT IMPROVEMENTS DEMONSTRATION")
    print("=" * 80)
    
    # Sample problematic message from the issue
    message = "Ищу мужа на час, не сложная помощь по дому"
    instructions = """1. **Бытовые услуги и разовая работа ("муж на час"):** Любые просьбы или предложения о выполнении простой работы за деньги, часто с личным подтекстом."""
    
    print(f"\nSample spam message: '{message}'")
    print(f"Instructions: {instructions[:100]}...")
    
    print("\n" + "=" * 40)
    print("OLD PROMPT STRUCTURE (WEAK):")
    print("=" * 40)
    
    old_system = f"Является ли спамом сообщение от пользователя? Важные признаки спам-сообщений: {instructions}"
    old_user = f"{message}"
    
    print("SYSTEM:")
    print(f"'{old_system}'")
    print("\nUSER:")
    print(f"'{old_user}'")
    
    print("\n" + "=" * 40)
    print("NEW PROMPT STRUCTURE (IMPROVED):")
    print("=" * 40)
    
    new_system = f"""Ты - эксперт по обнаружению спама в групповых чатах. Твоя задача - точно определить, является ли данное сообщение спамом.

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

    new_user = f"Проанализируй это сообщение и определи, является ли оно спамом:\n\n\"{message}\""
    
    print("SYSTEM:")
    print(f"'{new_system}'")
    print("\nUSER:")
    print(f"'{new_user}'")
    
    print("\n" + "=" * 40)
    print("KEY IMPROVEMENTS:")
    print("=" * 40)
    print("1. ✓ Expert role establishment ('эксперт по обнаружению спама')")
    print("2. ✓ Explicit strictness instruction ('должен быть строгим')")  
    print("3. ✓ Clear warning about 'harmless' requests being spam")
    print("4. ✓ Bullet-point reminders of key spam indicators")
    print("5. ✓ Structured analytical user message")
    print("6. ✓ Emphasized JSON response format")
    print("7. ✓ Much more directive and specific language")

def show_false_negative_examples():
    """Show the specific false negative examples that should now be caught"""
    
    print("\n" + "=" * 40)
    print("FALSE NEGATIVE EXAMPLES TO CATCH:")
    print("=" * 40)
    
    examples = [
        "Привет, кто сможет помочь закончить ремонт? Уже нет сил самой делать его. Заплачу 5000",
        "Срочно требуется помощь сегодня завтра, 8600 рублей..",
        "Приветик ) У кого есть желание поговорить, или выйти пройтись пишите", 
        "требуются 2 человека на выгрузку коробок из машины, два часа работы, заплачу каждому по 3000р",
        "Ищу мужа на час, не сложная помощь по дому"
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"{i}. '{example}'")
        
        # Classify each example
        if "заплачу" in example.lower() or "рублей" in example.lower() or "3000р" in example:
            spam_type = "💰 Payment for work/services"
        elif "поговорить" in example.lower() or "пройтись" in example.lower():
            spam_type = "💬 Inappropriate socializing"
        elif "муж на час" in example.lower():
            spam_type = "🔧 'Husband for an hour' services"
        else:
            spam_type = "🚩 General spam indicators"
            
        print(f"   → Expected: SPAM ({spam_type})")
        print()

if __name__ == "__main__":
    show_old_vs_new_prompt()
    show_false_negative_examples()
    
    print("\n" + "=" * 80)
    print("EXPECTED IMPACT:")
    print("=" * 80)
    print("The improved prompt structure should significantly reduce false negatives by:")
    print("• Being more authoritative and directive")
    print("• Providing explicit examples of what constitutes spam")  
    print("• Warning against classifying obvious spam as 'harmless requests'")
    print("• Using clear, structured instructions")
    print("• Emphasizing strict classification standards")
    print("\nNext step: Test with actual OpenAI API to validate improvements")