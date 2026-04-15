import re
from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agendamentos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_vet'  # Chave secreta para sessões
db = SQLAlchemy(app)

users = {
    'doutora1': {'name': 'Doutora 1', 'password': 'vet123', 'role': 'doctor'},
    'doutora2': {'name': 'Doutora 2', 'password': 'vet456', 'role': 'doctor'},
    'recepcao': {'name': 'Recepção', 'password': 'vetkap', 'role': 'reception'},
}

class Agendamento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome_dono = db.Column(db.String(100), nullable=False)
    nome_pet = db.Column(db.String(100), nullable=False)
    especie = db.Column(db.String(20), nullable=False)
    sexo = db.Column(db.String(10), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    data = db.Column(db.DateTime, nullable=False)
    servico = db.Column(db.String(200), nullable=False)
    doutora = db.Column(db.String(50), nullable=False)
    motivo = db.Column(db.Text, nullable=False)

    def __repr__(self):
        return f'<Agendamento {self.id}>'

@app.route('/')
def index():
    return redirect(url_for('cliente'))

@app.route('/cliente')
def cliente():
    return render_template('cliente.html')

@app.route('/agendar', methods=['POST'])
def agendar():
    nome_dono = request.form.get('nome_dono', '').strip()
    nome_pet = request.form.get('nome_pet', '').strip()
    especie = request.form.get('especie', '').strip()
    sexo = request.form.get('sexo', '').strip()
    telefone = request.form.get('telefone', '').strip()
    data_str = request.form.get('data', '').strip()
    servico = request.form.get('servico', '').strip()
    doutora = request.form.get('doutora', 'Doutora 1').strip()
    motivo = request.form.get('motivo', '').strip()

    if not (nome_dono and nome_pet and especie and sexo and telefone and data_str and servico and doutora and motivo):
        return render_template('cliente.html', erro='Todos os campos são obrigatórios')

    telefone_pattern = re.compile(r'^\(?\d{2}\)?\s?\d{4,5}-?\d{4}$')
    if not telefone_pattern.match(telefone):
        return render_template('cliente.html', erro='Telefone inválido. Use o formato (XX) XXXXX-XXXX ou XXXXXXXXXXX.')

    # Converter string para datetime
    data = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
    fim = data + timedelta(minutes=40)

    # Bloquear 40 minutos para o mesmo médico
    conflito = False
    for agendamento in Agendamento.query.filter_by(doutora=doutora).all():
        inicio_existente = agendamento.data
        fim_existente = inicio_existente + timedelta(minutes=40)
        if data < fim_existente and fim > inicio_existente:
            conflito = True
            break

    if conflito:
        return render_template('cliente.html', erro='Horário indisponível para esta doutora. Escolha outro horário.')

    novo_agendamento = Agendamento(nome_dono=nome_dono, nome_pet=nome_pet, especie=especie, sexo=sexo, telefone=telefone, data=data, servico=servico, doutora=doutora, motivo=motivo)
    db.session.add(novo_agendamento)
    db.session.commit()

    session['last_agendamento_id'] = novo_agendamento.id
    return redirect(url_for('confirmacao'))

@app.route('/confirmacao')
def confirmacao():
    agendamento_id = session.pop('last_agendamento_id', None)
    if not agendamento_id:
        return redirect(url_for('cliente'))
    agendamento = Agendamento.query.get_or_404(agendamento_id)
    return render_template('confirmacao.html', agendamento=agendamento)

@app.route('/painel')
def painel():
    user = session.get('user')
    role = session.get('role')
    if not user:
        return redirect(url_for('login_page'))
    if role == 'reception':
        agendamentos = Agendamento.query.all()
    else:
        agendamentos = Agendamento.query.filter_by(doutora=user).all()
    return render_template('painel.html', agendamentos=agendamentos, doctor=user, role=role)

@app.route('/veterinario')
def veterinario_alias():
    return redirect(url_for('painel'))

@app.route('/login', methods=['GET'])
def login_page():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    senha = request.form.get('senha', '')
    if username in users and users[username]['password'] == senha:
        session['user'] = users[username]['name']
        session['role'] = users[username]['role']
        session['logged_in'] = True
        return redirect(url_for('painel'))
    return render_template('login.html', erro='Usuário ou senha incorretos')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('user', None)
    session.pop('role', None)
    return redirect(url_for('cliente'))

@app.route('/deletar/<int:id>', methods=['POST'])
def deletar(id):
    if 'logged_in' not in session:
        return redirect(url_for('login_page'))
    agendamento = Agendamento.query.get_or_404(id)
    db.session.delete(agendamento)
    db.session.commit()
    return redirect(url_for('painel'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()

        # Verifica coluna doutora na tabela agendamento, adiciona se não existir
        with db.engine.connect() as conn:
            result = conn.execute(db.text("PRAGMA table_info(agendamento)"))
            columns = [row[1] for row in result]
            if 'doutora' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN doutora VARCHAR(50) DEFAULT 'Doutora 1'"))
                    print('Coluna doutora adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna doutora:', e)
            if 'telefone' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN telefone VARCHAR(20) DEFAULT ''"))
                    print('Coluna telefone adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna telefone:', e)
            if 'especie' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN especie VARCHAR(20) DEFAULT 'Cachorro'"))
                    print('Coluna especie adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna especie:', e)
            if 'sexo' not in columns:
                try:
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN sexo VARCHAR(10) DEFAULT 'Macho'"))
                    print('Coluna sexo adicionada à tabela agendamento')
                except Exception as e:
                    print('Falha ao adicionar coluna sexo:', e)
    app.run(debug=True, host='0.0.0.0', port=5001)