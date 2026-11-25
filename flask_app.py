import os
import random
import string
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, render_template_string
from flask_sqlalchemy import SQLAlchemy
import boto3
from botocore.client import Config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(BASE_DIR, 'fullmark_platform.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fullmark-mr-mohamed-said-2026')

db = SQLAlchemy(app)

# ================= إعدادات سحابة Backblaze B2 =================
B2_ENDPOINT = "https://s3.eu-central-003.backblazeb2.com"
B2_KEY_ID = os.environ.get("B2_KEY_ID", "PUT_YOUR_KEY_ID_HERE")
B2_APP_KEY = os.environ.get("B2_APP_KEY", "PUT_YOUR_APPLICATION_KEY_HERE")
BUCKET_NAME = "fullmark-mohamed-said"

s3_client = boto3.client(
    's3',
    endpoint_url=B2_ENDPOINT,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APP_KEY,
    config=Config(signature_version='s3v4')
)


# ================= دالة التشفير السريع للفيديوهات الأوفلاين =================
def xor_crypt(data: bytes, key: str) -> bytes:
    """تشفير وفك تشفير الفيديو بمفتاح الحصة السري بدون استهلاك رامات الموبايل"""
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    return bytes([b ^ key_bytes[i % key_len] for i, b in enumerate(data)])


# ================= جداول قاعدة البيانات (Database) =================
class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    parent_phone = db.Column(db.String(15), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    device_id = db.Column(db.String(100), nullable=True)


class Lesson(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    unit_name = db.Column(db.String(100), nullable=False)
    grade = db.Column(db.String(20), nullable=False)
    b2_video_key = db.Column(db.String(255), nullable=False)
    encryption_key = db.Column(db.String(32), nullable=False)


class ActivationCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('lesson.id'), nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    used_by_phone = db.Column(db.String(15), nullable=True)
    offline_expiry = db.Column(db.DateTime, nullable=True)


def generate_fm_code():
    p1 = ''.join(random.choices(string.digits, k=4))
    p2 = ''.join(random.choices(string.digits, k=4))
    return f"FM-{p1}-{p2}"


# ================= واجهة الموبايل والويب (Full Mark UI) =================
HTML_UI = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Full Mark - Mr. Mohamed Saeed</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;700;900&display=swap" rel="stylesheet">
    <style>body { font-family: 'Cairo', sans-serif; user-select: none; }</style>
</head>
<body class="bg-slate-900 text-white min-h-screen pb-20">
    <!-- الهيدر -->
    <header class="bg-gradient-to-l from-indigo-900 to-blue-900 p-4 shadow-lg border-b border-blue-700 flex justify-between items-center">
        <div>
            <span class="bg-yellow-400 text-slate-900 text-xs font-black px-2 py-0.5 rounded">FULL MARK</span>
            <h1 class="text-lg font-bold mt-1">مستر محمد سعيد - لغة إنجليزية</h1>
        </div>
        <div class="text-left text-xs text-blue-200">
            <p>حالة الاتصال: <span id="net-status" class="text-green-400 font-bold">أونلاين</span></p>
            <p>ID الجهاز: <span class="font-mono">FM-DEV-01</span></p>
        </div>
    </header>

    <div class="p-4 max-w-md mx-auto space-y-5">
        <!-- تفعيل كود السنتر -->
        <div class="bg-slate-800 p-4 rounded-2xl border border-slate-700 shadow">
            <h2 class="text-sm font-bold text-yellow-400 mb-2">⚡ شحن كود حصة (كارت Full Mark)</h2>
            <div class="flex gap-2">
                <input id="code-input" type="text" placeholder="FM-XXXX-XXXX" class="w-full bg-slate-900 border border-slate-600 rounded-xl px-3 py-2 text-center font-mono uppercase text-sm">
                <button onclick="activateCode()" class="bg-blue-600 hover:bg-blue-500 px-4 py-2 rounded-xl font-bold text-sm whitespace-nowrap">تفعيل</button>
            </div>
            <p id="msg" class="text-xs mt-2 hidden"></p>
        </div>

        <!-- قائمة الحصص -->
        <div>
            <h2 class="text-base font-bold mb-3 flex items-center justify-between">
                <span>📚 حصص الصف الأول الثانوي</span>
                <span class="text-xs text-slate-400">مذكرة Full Mark مرفقة</span>
            </h2>
            <div class="space-y-3">
                {% for lesson in lessons %}
                <div class="bg-slate-800 p-4 rounded-2xl border border-slate-700">
                    <div class="flex justify-between items-start">
                        <div>
                            <span class="text-xs bg-indigo-900 text-indigo-200 px-2 py-0.5 rounded">{{ lesson.unit_name }}</span>
                            <h3 class="font-bold text-sm mt-1">{{ lesson.title }}</h3>
                        </div>
                        <span class="text-xs text-emerald-400 font-bold">مشفرة 🔒</span>
                    </div>
                    <div class="mt-4 flex gap-2">
                        <button onclick="getOfflineLink({{ lesson.id }})" class="flex-1 bg-emerald-600 hover:bg-emerald-500 py-2 rounded-xl text-xs font-bold">
                            📥 تحميل للمشاهدة بدون نت
                        </button>
                        <button class="bg-slate-700 px-3 py-2 rounded-xl text-xs font-bold">
                            📄 مذكرة Full Mark
                        </button>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <!-- صندوق الأكواد التجريبية للمستر -->
        <div class="bg-slate-950 p-3 rounded-xl border border-dashed border-slate-700 text-xs">
            <p class="font-bold text-yellow-400 mb-1">🛠️ لوحة التجربة السريعة (أكواد شغالة للتجربة):</p>
            {% for c in codes %}
                <span class="inline-block bg-slate-800 font-mono px-2 py-1 rounded m-1">{{ c.code }} ({{ 'مستخدم' if c.is_used else 'متاح' }})</span>
            {% endfor %}
        </div>
    </div>

    <script>
        async function activateCode() {
            const code = document.getElementById('code-input').value.trim();
            const res = await fetch('/api/activate', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code: code, phone: '01000000000'})
            });
            const data = await res.json();
            const msg = document.getElementById('msg');
            msg.classList.remove('hidden');
            msg.className = 'text-xs mt-2 font-bold ' + (data.status === 'success' ? 'text-green-400' : 'text-red-400');
            msg.innerText = data.message;
            if(data.status === 'success') setTimeout(() => location.reload(), 1200);
        }

        async function getOfflineLink(lessonId) {
            const res = await fetch('/api/offline_access/' + lessonId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone: '01000000000'})
            });
            const data = await res.json();
            if(data.status === 'success') {
                alert('✅ تم التوثيق!\\nمفتاح فك التشفير للأوفلاين: ' + data.encryption_key + '\\nصالح بدون نت حتى: ' + data.valid_until + '\\nالعلامة المائية: ' + data.watermark);
            } else {
                alert('❌ ' + data.message);
            }
        }
    </script>
</body>
</html>
"""


# ================= المسارات والـ APIs =================
@app.route('/')
def index():
    lessons = Lesson.query.all()
    codes = ActivationCode.query.all()
    return render_template_string(HTML_UI, lessons=lessons, codes=codes)


@app.route('/api/activate', methods=['POST'])
def activate_code():
    data = request.get_json(silent=True) or {}
    code_str = data.get('code', '').upper()
    phone = data.get('phone', '01000000000')

    code_obj = ActivationCode.query.filter_by(code=code_str).first()
    if not code_obj:
        return jsonify({"status": "error", "message": "كود Full Mark غير صحيح!"})
    if code_obj.is_used:
        return jsonify({"status": "error", "message": "هذا الكود تم استخدامه من قبل!"})

    code_obj.is_used = True
    code_obj.used_by_phone = phone
    code_obj.offline_expiry = datetime.utcnow() + timedelta(days=7)
    db.session.commit()
    return jsonify({"status": "success", "message": "تم تفعيل الحصة بنجاح! يمكنك الآن تحميلها بدون إنترنت."})


@app.route('/api/offline_access/<int:lesson_id>', methods=['POST'])
def offline_access(lesson_id):
    data = request.get_json(silent=True) or {}
    phone = data.get('phone', '01000000000')
    sub = ActivationCode.query.filter_by(lesson_id=lesson_id, used_by_phone=phone, is_used=True).first()
    if not sub:
        return jsonify({"status": "error", "message": "لازم تفعل الحصة بكود Full Mark الأول من المربع اللي فوق!"})

    lesson = Lesson.query.get_or_404(lesson_id)
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': lesson.b2_video_key},
            ExpiresIn=1800
        )
    except Exception:
        url = "local_test_url"

    return jsonify({
        "status": "success",
        "download_url": url,
        "encryption_key": lesson.encryption_key,
        "valid_until": sub.offline_expiry.strftime('%Y-%m-%d %H:%M'),
        "watermark": f"Full Mark - {phone}"
    })


def seed_initial_data():
    if Lesson.query.count() == 0:
        l1 = Lesson(
            title="Lesson 1: Present Perfect & Vocabulary",
            unit_name="Unit 1 - Full Mark",
            grade="1st_sec",
            b2_video_key="unit1_lesson1.mp4.enc",
            encryption_key="FM_SECRET_KEY_99281"
        )
        db.session.add(l1)
        db.session.commit()
        for _ in range(3):
            db.session.add(ActivationCode(code=generate_fm_code(), lesson_id=l1.id))
        db.session.commit()


# إنشاء الجداول والبيانات الأولية تلقائياً عند تشغيل WSGI على PythonAnywhere
with app.app_context():
    db.create_all()
    seed_initial_data()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)