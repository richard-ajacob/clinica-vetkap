import re
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from sqlalchemy import or_

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///agendamentos.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'chave_secreta_vet'  # Chave secreta para sessões
db = SQLAlchemy(app)

INTERVALO_MINUTOS = 40
JANELAS_ATENDIMENTO = {
    'Doutora 1': ((8, 30), (13, 0)),
    'Doutora 2': ((8, 30), (13, 0)),
    'Doutora 3': ((14, 0), (18, 30)),
    'Doutora 4': ((14, 0), (18, 30)),
}
DOUTORAS = list(JANELAS_ATENDIMENTO.keys())

class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    senha = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False)

    def __repr__(self):
        return f'<Usuario {self.username}>'

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


def gerar_horarios_disponiveis(doutora, data_consulta):
    janela = JANELAS_ATENDIMENTO.get(doutora)
    if not janela:
        return []

    (hora_inicio, minuto_inicio), (hora_fim, minuto_fim) = janela
    inicio_dia = datetime.combine(data_consulta, datetime.min.time()).replace(hour=hora_inicio, minute=minuto_inicio)
    fim_dia = datetime.combine(data_consulta, datetime.min.time()).replace(hour=hora_fim, minute=minuto_fim)
    agora_limite = datetime.now() + timedelta(minutes=INTERVALO_MINUTOS)
    intervalo = timedelta(minutes=INTERVALO_MINUTOS)

    agendamentos = Agendamento.query.filter_by(doutora=doutora).all()
    agendamentos_no_dia = [a for a in agendamentos if a.data.date() == data_consulta]

    horarios = []
    horario_atual = inicio_dia

    while horario_atual + intervalo <= fim_dia:
        fim_horario = horario_atual + intervalo

        if data_consulta == datetime.now().date() and horario_atual < agora_limite:
            horario_atual += intervalo
            continue

        conflito = False
        for agendamento in agendamentos_no_dia:
            inicio_existente = agendamento.data
            fim_existente = inicio_existente + intervalo
            if horario_atual < fim_existente and fim_horario > inicio_existente:
                conflito = True
                break

        if not conflito:
            horarios.append(horario_atual.strftime('%H:%M'))

        horario_atual += intervalo

    return horarios

@app.route('/')
def index():
    return redirect(url_for('cliente'))

@app.route('/cliente')
def cliente():
    return render_template('cliente.html')


@app.route('/horarios-disponiveis')
def horarios_disponiveis():
    doutora = request.args.get('doutora', '').strip()
    data_str = request.args.get('data', '').strip()

    if not doutora or not data_str:
        return jsonify({'horarios': []})

    try:
        data_consulta = datetime.strptime(data_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'horarios': [], 'erro': 'Data inválida'}), 400

    horarios = gerar_horarios_disponiveis(doutora, data_consulta)
    return jsonify({'horarios': horarios})

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
    try:
        data = datetime.strptime(data_str, '%Y-%m-%dT%H:%M')
    except ValueError:
        return render_template('cliente.html', erro='Data ou horário inválido.')

    horarios_disponiveis_data = gerar_horarios_disponiveis(doutora, data.date())
    if data.strftime('%H:%M') not in horarios_disponiveis_data:
        return render_template('cliente.html', erro='Horário fora do período da doutora ou já indisponível. Escolha outro horário.')

    fim = data + timedelta(minutes=INTERVALO_MINUTOS)

    # Bloquear janela de atendimento para a mesma doutora
    conflito = False
    for agendamento in Agendamento.query.filter_by(doutora=doutora).all():
        inicio_existente = agendamento.data
        fim_existente = inicio_existente + timedelta(minutes=INTERVALO_MINUTOS)
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
    pagina = request.args.get('pagina', default=1, type=int)
    if not pagina or pagina < 1:
        pagina = 1

    nome_filtro = request.args.get('nome', '').strip()
    data_filtro = request.args.get('data', '').strip()
    doutora_filtro = request.args.get('doutora', '').strip()
    servico_filtro = request.args.get('servico', '').strip()
    especie_filtro = request.args.get('especie', '').strip()
    sexo_filtro = request.args.get('sexo', '').strip()
    filtro_erro = ''

    if role == 'reception':
        base_query = Agendamento.query
        doctor_options = DOUTORAS
    else:
        base_query = Agendamento.query.filter_by(doutora=user)
        doctor_options = [user]
        doutora_filtro = user

    service_options = [
        servico for servico, in base_query.with_entities(Agendamento.servico).distinct().order_by(Agendamento.servico).all()
        if servico
    ]
    if 'Consulta' not in service_options:
        service_options.insert(0, 'Consulta')

    especie_options = ['Canino', 'Felino']
    sexo_options = ['Macho', 'Fêmea']

    query = base_query

    if nome_filtro:
        termo = f'%{nome_filtro}%'
        query = query.filter(
            or_(
                Agendamento.nome_dono.ilike(termo),
                Agendamento.nome_pet.ilike(termo)
            )
        )

    if data_filtro:
        try:
            data_inicial = datetime.strptime(data_filtro, '%Y-%m-%d')
            data_final = data_inicial + timedelta(days=1)
            query = query.filter(Agendamento.data >= data_inicial, Agendamento.data < data_final)
        except ValueError:
            filtro_erro = 'Data do filtro inválida.'

    if role == 'reception' and doutora_filtro:
        query = query.filter_by(doutora=doutora_filtro)

    if servico_filtro:
        query = query.filter_by(servico=servico_filtro)

    if especie_filtro:
        query = query.filter_by(especie=especie_filtro)

    if sexo_filtro:
        query = query.filter_by(sexo=sexo_filtro)

    paginacao = query.order_by(Agendamento.data.asc()).paginate(page=pagina, per_page=10, error_out=False)
    agendamentos = paginacao.items
    filtros = {
        'nome': nome_filtro,
        'data': data_filtro,
        'doutora': doutora_filtro,
        'servico': servico_filtro,
        'especie': especie_filtro,
        'sexo': sexo_filtro,
    }
    query_params = {chave: valor for chave, valor in filtros.items() if valor}

    return render_template(
        'painel.html',
        agendamentos=agendamentos,
        paginacao=paginacao,
        doctor=user,
        role=role,
        filtros=filtros,
        query_params=query_params,
        doctor_options=doctor_options,
        service_options=service_options,
        especie_options=especie_options,
        sexo_options=sexo_options,
        filtro_erro=filtro_erro,
    )

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

    usuario = Usuario.query.filter_by(username=username).first()
    if usuario and usuario.senha == senha:
        session['user'] = usuario.nome
        session['role'] = usuario.role
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

        usuarios_padrao = [
            {'username': 'doutora1', 'nome': 'Doutora 1', 'senha': 'vet123', 'role': 'doctor'},
            {'username': 'doutora2', 'nome': 'Doutora 2', 'senha': 'vet456', 'role': 'doctor'},
            {'username': 'doutora3', 'nome': 'Doutora 3', 'senha': 'vet789', 'role': 'doctor'},
            {'username': 'doutora4', 'nome': 'Doutora 4', 'senha': 'vet101', 'role': 'doctor'},
            {'username': 'recepcao', 'nome': 'Recepção', 'senha': 'vetkap', 'role': 'reception'},
        ]

        for usuario_data in usuarios_padrao:
            usuario = Usuario.query.filter_by(username=usuario_data['username']).first()
            if usuario:
                usuario.nome = usuario_data['nome']
                usuario.senha = usuario_data['senha']
                usuario.role = usuario_data['role']
            else:
                db.session.add(Usuario(**usuario_data))
        db.session.commit()

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
                    conn.execute(db.text("ALTER TABLE agendamento ADD COLUMN especie VARCHAR(20) DEFAULT 'Canino'"))
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