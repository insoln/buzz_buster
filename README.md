# Buzz Buster

Бот для Telegram, предназначенный для ловли определенного типа спама в группах. Принцип действия: первое сообщение от пользователя после присоединения его к группе отправляется на проверку в GPT, если бездушная машина определяет наличие спама - пользователь блокируется во всех группах, где включен бот.

## Возможности

- Автоматическое обнаружение и удаление спама по астраиваемым критериям
- Легкость установки и использования

## Установка

1. Клонируйте репозиторий:
    ```sh
    git clone https://github.com/insoln/buzz_buster
    cd buzz_buster
    ```
2. Настройте переменные окружения. Создайте файл `.env` и пропишите там необходимые переменные:
    ```sh
    cp .env.example .env
    ```

    ```properties
    # Telegram Bot
    TELEGRAM_API_KEY=your_telegram_api_key      # Токен бота (из @BotFather)

    # OpenAI
    OPENAI_API_KEY=your_openai_api_key          # OpenAI API-ключ

    # Telegram Admin
    ADMIN_TELEGRAM_ID=your_admin_telegram_id    # Telegram ID администратора бота

    # Status Logging
    STATUSCHAT_TELEGRAM_ID=your_logs_chat_id    # Telegram ID чата для логов

    # Критерии спама
    INSTRUCTIONS_DEFAULT_TEXT=Любые спам-признаки.
    ```

    Данные бота хранятся в базе MySQL, которая поднимается в параллельном контейнере. При желании можно использовать внешний сервер MySQL, тогда в .env нужно раскомментировать соответствующие строки, а в docker-compose.yml, наоборот, закомментировать

3. Запустите docker:
    ```sh
    docker compose up --build -d
    ```

## Использование

1. Добавьте бота в вашу группу Telegram
2. Предоставьте ему права администратор (как минимум права на удаление сообщений и бан пользователей)
3. Выполните команду /start, чтобы бот начал защищать группу от спама
4. Если стандартные критерии проверки на спам не подходят для конкретной группы (например, в группе активно обсуждается быстрый заработок, и сообщение с подобным контекстом не должно восприниматься как спам), можно задать кастомные критерии командой /set instructions <новые критерии>

    ```plaintext
    /set instructions Текст содержит гомоглифические подстановки или больше 5 следующих подряд эмодзи.
    ```

### Как развернуть бота для разработки?

Бот разработан в среде VS Code. Папка .devcontainer позволяет использовать расширение, которое развернет для разработки отдельный контейнер и откроет окно, в котором можно дебажить код.

#### Шаги для развертывания:

1. Установите [Visual Studio Code](https://code.visualstudio.com/).
2. Установите [Remote - Containers](https://aka.ms/vscode-remote/download/extension) расширение для VS Code.
3. Откройте проект в VS Code.
4. Нажмите `F1`, введите ` Dev Containers: Open Folder in Container...` и выберите текущую папку проекта.
5. Дождитесь, пока контейнер будет развернут и запущен. Может понадобиться несколько секунд на то, чтобы все расширения корректно установились в контейнер.

### Как получить поддержку?

Если у вас возникли проблемы или вопросы, откройте issue на GitHub. Пуллреквесты приветствуются.