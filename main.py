import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
import sqlite3
import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Состояния для ConversationHandler
ADD_STUDENT, ADD_SUBJECT, CHOOSE_SUBJECT, INPUT_DATE, MARK_ATTENDANCE = range(5)

# Инициализация базы данных (остается без изменений)
def init_db():
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject_id INTEGER,
            date TEXT,
            status BOOLEAN,
            FOREIGN KEY (student_id) REFERENCES students (id),
            FOREIGN KEY (subject_id) REFERENCES subjects (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# ================== MARK ATTENDANCE LOGIC ==================

async def mark_attendance_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса отметки посещаемости - показываем список предметов"""
    
    # Очищаем предыдущие данные
    context.user_data.clear()
    
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Получаем список предметов
    cursor.execute("SELECT name FROM subjects")
    subjects = cursor.fetchall()
    conn.close()
    
    if not subjects:
        await update.message.reply_text('Сначала добавьте предметы через /add_subject!')
        return ConversationHandler.END
    
    # Создаем клавиатуру с предметами
    keyboard = [[subject[0]] for subject in subjects]
    keyboard.append(['/cancel']) # Добавляем кнопку отмены
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        '🎓 Выберите предмет для отметки посещаемости:',
        reply_markup=reply_markup
    )
    
    return CHOOSE_SUBJECT

async def choose_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора предмета"""
    
    subject_name = update.message.text
    
    # Проверяем существование предмета в базе
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM subjects WHERE name = ?", (subject_name,))
    subject_result = cursor.fetchone()
    conn.close()
    
    if not subject_result:
        await update.message.reply_text('❌ Предмет не найден! Выберите предмет из списка.')
        return CHOOSE_SUBJECT
    
    # Сохраняем данные предмета
    context.user_data['subject'] = subject_name
    context.user_data['subject_id'] = subject_result[0]
    
    await update.message.reply_text(
        f'📅 Теперь введите дату в формате ГГГГ-ММ-ДД (например, {datetime.datetime.now().strftime("%Y-%m-%d")}):',
        reply_markup=ReplyKeyboardRemove()
    )
    
    return INPUT_DATE

async def input_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода даты"""
    
    date = update.message.text
    
    # Проверяем формат даты
    try:
        datetime.datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        await update.message.reply_text('❌ Неверный формат даты! Используйте ГГГГ-ММ-ДД (например, 2024-01-15)')
        return INPUT_DATE
    
    # Сохраняем дату
    context.user_data['date'] = date
    
    # Переходим к отметке посещаемости
    return await show_students_for_attendance(update, context)

async def show_students_for_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показываем список студентов для отметки посещаемости"""
    
    # Проверяем, что у нас есть все необходимые данные
    if 'subject_id' not in context.user_data or 'date' not in context.user_data:
        await update.message.reply_text('❌ Ошибка: потеряны данные. Начните заново с /mark_attendance')
        return ConversationHandler.END
    
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Получаем список студентов
    cursor.execute("SELECT id, name FROM students")
    students = cursor.fetchall()
    
    if not students:
        await update.message.reply_text('❌ Сначала добавьте студентов через /add_student!')
        conn.close()
        return ConversationHandler.END
    
    # Сохраняем студентов в context для дальнейшего использования
    context.user_data['students'] = students
    
    # Создаем клавиатуру со студентами и их текущим статусом
    keyboard = []
    for student_id, student_name in students:
        # Проверяем текущий статус посещаемости
        cursor.execute('''SELECT status FROM attendance 
                          WHERE student_id = ? AND subject_id = ? AND date = ?''',
                       (student_id, context.user_data['subject_id'], context.user_data['date']))
        existing = cursor.fetchone()
        
        status = "✅" if existing and existing[0] else "❌"
        keyboard.append([f"{student_name} - {status}"])
    
    keyboard.append(['/save', '/cancel']) # Кнопки сохранения и отмены
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    conn.close()
    
    await update.message.reply_text(
        f'🎯 Отмечайте посещаемость для предмета "{context.user_data["subject"]}" на дату {context.user_data["date"]}:\n\n'
        'Нажимайте на студента для изменения статуса (✅/❌)\n'
        'Используйте /save для сохранения или /cancel для отмены',
        reply_markup=reply_markup
    )
    
    return MARK_ATTENDANCE

async def toggle_student_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия на студента - изменение статуса посещаемости"""
    
    # Проверяем, что у нас есть все необходимые данные
    if 'students' not in context.user_data:
        await update.message.reply_text('❌ Ошибка: потеряны данные. Начните заново с /mark_attendance')
        return ConversationHandler.END
    
    student_text = update.message.text
    
    # Извлекаем имя студента из текста (формат: "Имя - ✅" или "Имя - ❌")
    if ' - ' in student_text:
        student_name = student_text.split(' - ')[0]
    else:
        # Если формат неправильный, просто обновляем список
        return await show_students_for_attendance(update, context)
    
    # Находим ID студента
    student_id = None
    for student in context.user_data['students']:
        if student[1] == student_name:
            student_id = student[0]
            break
    
    if student_id is None:
        await update.message.reply_text('❌ Студент не найден!')
        return await show_students_for_attendance(update, context)
    
    # Обновляем статус в базе данных
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    # Проверяем текущий статус
    cursor.execute('''SELECT id, status FROM attendance 
                      WHERE student_id = ? AND subject_id = ? AND date = ?''',
                   (student_id, context.user_data['subject_id'], context.user_data['date']))
    existing = cursor.fetchone()
    
    # Инвертируем статус (если был True -> False, если False -> True, если нет записи -> True)
    new_status = not existing[1] if existing else True
    
    if existing:
        # Обновляем существующую запись
        cursor.execute('''UPDATE attendance SET status = ? 
                          WHERE student_id = ? AND subject_id = ? AND date = ?''',
                       (new_status, student_id, context.user_data['subject_id'], context.user_data['date']))
    else:
        # Создаем новую запись
        cursor.execute('''INSERT INTO attendance (student_id, subject_id, date, status)
                          VALUES (?, ?, ?, ?)''',
                       (student_id, context.user_data['subject_id'], context.user_data['date'], new_status))
    
    conn.commit()
    conn.close()
    
    # Обновляем отображение списка студентов
    return await show_students_for_attendance(update, context)

async def save_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение посещаемости и завершение процесса"""
    
    await update.message.reply_text(
        f'✅ Посещаемость для предмета "{context.user_data["subject"]}" на дату {context.user_data["date"]} сохранена!',
        reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
    )
    
    # Очищаем временные данные
    context.user_data.clear()
    
    return ConversationHandler.END

async def cancel_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена процесса отметки посещаемости"""
    
    await update.message.reply_text(
        '❌ Отметка посещаемости отменена.',
        reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
    )
    
    # Очищаем временные данные
    context.user_data.clear()
    
    return ConversationHandler.END

# ================== OTHER FUNCTIONS (остаются без изменений) ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [['/add_student', '/add_subject'], 
                ['/mark_attendance', '/show_attendance']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        'Выберите действие:',
        reply_markup=reply_markup
    )

async def add_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Введите имя студента:',
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_STUDENT

async def save_student(update: Update, context: ContextTypes.DEFAULT_TYPE):
    student_name = update.message.text
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("INSERT INTO students (name) VALUES (?)", (student_name,))
        conn.commit()
        await update.message.reply_text(f'✅ Студент {student_name} добавлен!')
    except sqlite3.IntegrityError:
        await update.message.reply_text('❌ Этот студент уже существует!')
    
    conn.close()
    return ConversationHandler.END

async def add_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        'Введите название предмета:',
        reply_markup=ReplyKeyboardRemove()
    )
    return ADD_SUBJECT

async def save_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subject_name = update.message.text
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("INSERT INTO subjects (name) VALUES (?)", (subject_name,))
        conn.commit()
        await update.message.reply_text(f'✅ Предмет {subject_name} добавлен!')
    except sqlite3.IntegrityError:
        await update.message.reply_text('❌ Этот предмет уже существует!')
    
    conn.close()
    return ConversationHandler.END

async def show_attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('attendance.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT s.name, sub.name, a.date, a.status 
        FROM attendance a
        JOIN students s ON a.student_id = s.id
        JOIN subjects sub ON a.subject_id = sub.id
        ORDER BY a.date DESC
        LIMIT 20
    ''')
    
    records = cursor.fetchall()
    conn.close()
    
    if not records:
        await update.message.reply_text('📊 Записей о посещаемости нет.')
        return
    
    response = "📊 Последние записи о посещаемости:\n\n"
    for record in records:
        status = "✅ Присутствовал" if record[3] else "❌ Отсутствовал"
        response += f"👤 Студент: {record[0]}\n📚 Предмет: {record[1]}\n📅 Дата: {record[2]}\n{status}\n\n"
    
    await update.message.reply_text(response)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        '❌ Операция отменена.',
        reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True)
    )
    return ConversationHandler.END

def main():
    init_db()
    
    application = Application.builder().token("8174797515:AAF-gcbiWYxIox2dARtlvQZIiXe3qOzCtK8").build()

    # ConversationHandler для добавления студента
    add_student_conv = ConversationHandler(
        entry_points=[CommandHandler('add_student', add_student)],
        states={
            ADD_STUDENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_student)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # ConversationHandler для добавления предмета
    add_subject_conv = ConversationHandler(
        entry_points=[CommandHandler('add_subject', add_subject)],
        states={
            ADD_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_subject)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # ConversationHandler для отметки посещаемости (ПЕРЕПИСАННЫЙ)
    mark_attendance_conv = ConversationHandler(
        entry_points=[CommandHandler('mark_attendance', mark_attendance_start)],
        states={
            CHOOSE_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, choose_subject)],
            INPUT_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_date)],
            MARK_ATTENDANCE: [
                MessageHandler(filters.Regex('^/save$'), save_attendance),
                MessageHandler(filters.TEXT & ~filters.COMMAND, toggle_student_attendance)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel_attendance)]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("show_attendance", show_attendance))
    application.add_handler(add_student_conv)
    application.add_handler(add_subject_conv)
    application.add_handler(mark_attendance_conv)

    application.run_polling()

if __name__ == '__main__':
    main()
