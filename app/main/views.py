import os
from flask import render_template, current_app, flash, redirect, session, url_for, request, g
from flask_login import login_user, logout_user, current_user, login_required
from app import db, lm, admin
from .forms import *
from . import main_bp
from app.models import User, ROLE_APPLICANT, ROLE_ADVISER, ROLE_ADMIN, Post, Comment, Preference, Favourite
from datetime import datetime
from app.emails import send_email
from werkzeug.utils import secure_filename
from flask_admin.contrib.sqla import ModelView
from flask_admin.contrib.fileadmin import FileAdmin
from pygeocoder import Geocoder
import os.path as op
from config import ADMINS

# file upload setting
UPLOAD_AGENT_FOLDER = 'app/static/agent_photo'
UPLOAD_HOUSE_FOLDER = 'app/static/house_photo'
ALLOWED_EXTENSIONS = set(['txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif'])
MAX_CONTENT_LENGTH = 16 * 1024 * 1024

# admin management setup
admin.add_view(ModelView(User, db.session))
admin.add_view(ModelView(Post, db.session))
path = op.join(os.path.abspath(__file__ + "/../../"), 'static')  # need to get parent path of this code
admin.add_view(FileAdmin(path, '/static/', name='Static Files'))


@main_bp.before_app_request
def before_request():
    g.user = current_user
    if g.user.is_authenticated:
        g.user.last_seen = datetime.utcnow()
        db.session.add(g.user)
        db.session.commit()


@main_bp.route('/list_post', methods=['GET', 'POST'])
@main_bp.route('/list_post/<int:page>', methods=['GET', 'POST'])
@login_required
def list_post(page=1):
    form = PeferForm()

    page = request.args.get('page', 1, type=int)
    pagination = Post.query.filter(Post.id == Post.id).order_by(Post.timestamp.desc()) \
        .paginate(page, per_page=current_app.config['FLASKY_POSTS_PER_PAGE'], error_out=False)

    posts = pagination.items

    if form.validate_on_submit() and current_user.role == ROLE_APPLICANT:
        pref = Preference(style=form.style.data, bedroom_no=form.bedroom_no.data,
                          bathroom_no=form.bathroom_no.data, garage_no=form.garage_no.data,
                          location=form.location.data, price=form.price.data)

        results = Post.query.filter(Post.style == pref.style).filter(Post.location == pref.location) \
            .filter(Post.price >= 0.8 * float(pref.price)).filter(Post.price <= 1.2 * float(pref.price)) \
            .filter(Post.bedroom_no >= pref.bedroom_no - 1).filter(Post.bedroom_no <= pref.bedroom_no + 1) \
            .order_by(Post.timestamp.desc())

        posts = results.paginate(page, current_app.config['FLASKY_POSTS_PER_PAGE'], False).items
        flash('Find ' + str(results.count()) + ' matching results')

    return render_template('list_post.html',
                           title='All the Houses',
                           posts=posts,
                           form=form,
                           pagination=pagination)


@main_bp.route('/list_agent', methods=['GET', 'POST'])
@main_bp.route('/list_agent/<int:page>', methods=['GET', 'POST'])
@login_required
def list_agent(page=1):
    users = User.query.filter(User.role == ROLE_ADVISER).paginate(page, current_app.config['FLASKY_POSTS_PER_PAGE'], False)

    return render_template('list_agent.html',
                           title='All the Agents',
                           users=users)


@main_bp.route('/', methods=['GET'])
@main_bp.route('/index', methods=['GET'])
def index():
    return render_template('index.html')


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS


@main_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditForm(current_user.nickname)
    if form.validate_on_submit():
        current_user.nickname = form.nickname.data
        current_user.phone = form.phone.data
        current_user.address = form.address.data
        current_user.about_me = form.about_me.data

        file = form.fileName.data
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = op.join(UPLOAD_AGENT_FOLDER, filename)
            file.save(file_path)
            # only when file is not none, change it, otherwise keep the previous one
            current_user.portrait = op.join('/static/agent_photo/', filename)

        if current_user.portrait is None:
            current_user.portrait = op.join('/static/agent_photo/', 'agent_default.gif')

        db.session.add(g.user)
        db.session.commit()
        flash('Your changes have been saved.')
        return redirect(url_for('.user', nickname=g.user.nickname))

    form.nickname.data = current_user.nickname
    form.phone.data = current_user.phone
    form.address.data = current_user.address
    form.about_me.data = current_user.about_me

    return render_template('edit_profile.html', form=form)


@main_bp.route('/preference', methods=['GET', 'POST'])
@login_required
def preference():
    form = PeferForm()
    user = g.user
    if form.validate_on_submit() and user.role == ROLE_APPLICANT:

        pref = Preference.query.filter_by(user_id=user.id).first()
        if pref is None:
            pref = Preference(style=form.style.data, bedroom_no=form.bedroom_no.data,
                              bathroom_no=form.bathroom_no.data, garage_no=form.garage_no.data,
                              location=form.location.data, price=form.price.data, user_id=user.id,
                              notify=form.notify.data)
        else:
            pref.style = form.style.data
            pref.bedroom_no = form.bedroom_no.data
            pref.bathroom_no = form.bathroom_no.data
            pref.garage_no = form.garage_no.data
            pref.location = form.location.data
            pref.price = form.price.data
            pref.notify = form.notify.data

        db.session.add(pref)
        db.session.commit()
        flash('Your preference is set! ')
        return redirect(url_for('.user', nickname=user.nickname))
    elif request.method != "POST" and user.pref is not None:
        form = PeferForm(obj=user.pref)

    return render_template('edit_preference.html', form=form)


def map_address(address):
    results = Geocoder.geocode(address)
    return str(results[0].coordinates).strip('()')


@main_bp.route('/edit_post/', methods=['GET', 'POST'])
@main_bp.route('/edit_post/<int:pid>', methods=['GET', 'POST'])
@login_required
def edit_post(pid=0):

    form = PostForm()
    post = Post.query.filter_by(id=pid).first()

    if form.validate_on_submit() and current_user.role == ROLE_ADVISER:

        if post is None:
            post = Post(title=form.title.data, body=form.body.data,
                        timestamp=datetime.utcnow(), user_id=current_user.id)
        else:
            post.title = form.title.data
            post.body = form.body.data
            post.timestamp = datetime.utcnow()
            post.user_id = user.id

        file = form.fileName.data
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = op.join(UPLOAD_HOUSE_FOLDER, filename)
            file.save(file_path)
            post.img = op.join('/static/house_photo/', filename)

        if post.img is None:
            post.img = op.join('/static/house_photo/', 'house_default.jpeg')

        post.location = form.location.data
        post.price = form.price.data
        post.style = form.style.data
        post.bedroom_no = form.bedroom_no.data
        post.bathroom_no = form.bathroom_no.data
        post.garage_no = form.garage_no.data
        post.address = form.address.data
        post.coordinate = map_address(post.address + " " + post.location)

        db.session.add(post)
        db.session.commit()
        flash("Your post is alive now. ")
        return redirect(url_for('.user', nickname=current_user.nickname))

    elif request.method != "POST":
        form = PostForm(obj=post)

    return render_template('edit_post.html', form=form)


@main_bp.route('/bookmark/<int:pid>', methods=['GET', 'POST'])
@login_required
def bookmark(pid):

    if Favourite.query.filter_by(id=str(current_user.id) + ':' + str(pid)).first():
        flash('The post was already in your collection.')
    else:
        fav = Favourite(current_user.id, pid)
        db.session.add(fav)
        db.session.commit()
        flash('The post was added in your collection.')

    return redirect(url_for('.list_post'))


@main_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    form = ContactForm()

    if request.method == 'POST':
        if form.validate() is False:
            flash('All fields are required.')
            return render_template('contact.html', form=form)
        else:
            #text_body = """
            #From: %s < %s >
            #%s """ % (form.name.data, form.email.data, form.message.data)
            #send_email(ADMINS[0], form.subject.data, text_body)
            send_email(ADMINS[0], form.subject.data, 'auth/contact', form=form)
            return render_template('contact.html', success=True)

    elif request.method == 'GET':
        return render_template('contact.html', form=form)


@main_bp.route('/home/<int:pid>', methods=['GET', 'POST'])
@login_required
def home(pid):
    post = Post.query.get_or_404(pid)
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data,
                          post=post,
                          author=current_user._get_current_object()
                          )
        db.session.add(comment)
        flash('Your comment has been published.')
        return redirect(url_for('.home', pid=post.id))
    page = request.args.get('page', 1, type=int)
    if page == -1:
        page = (post.comments.count() - 1) // \
               current_app.config['FLASKY_COMMENTS_PER_PAGE'] + 1
    pagination = post.comments.order_by(Comment.timestamp.asc())\
        .paginate(page, per_page=current_app.config['FLASKY_COMMENTS_PER_PAGE'], error_out=False)
    comments = pagination.items
    return render_template("home.html", post=post, form=form,
                           comments=comments, pagination=pagination)


@main_bp.route('/user/<nickname>', methods=['GET', 'POST'])
@main_bp.route('/user/<nickname>/<int:page>')
@login_required
def user(nickname, page=1):
    user = User.query.filter_by(nickname=nickname).first()

    if user is None:
        flash('User ' + nickname + ' not found.')
        return redirect(url_for('.index'))

    if user.role == ROLE_ADVISER:
        pagination = user.posts.paginate(page, current_app.config['FLASKY_POSTS_PER_PAGE'], False)
    elif user.role == ROLE_APPLICANT:
        favs = user.fav.all()
        idlist = []
        for fav in favs:
            idlist.append(fav.post_id)
        pagination = Post.query.filter(Post.id.in_(idlist)).paginate(page, current_app.config['FLASKY_POSTS_PER_PAGE'], False)

    posts = pagination.items
    return render_template('user.html', user=user, posts=posts, pagination=pagination)


@main_bp.route('/signout')
def signout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('.index'))


@main_bp.route('/delete/<int:id>')
@login_required
def delete(id):
    post = Post.query.get(id)
    if post is None:
        flash('Post not found.')
        return redirect(url_for('.index'))
    if post.author.id != g.user.id:
        flash('You cannot delete this post.')
        return redirect(url_for('.list_post'))
    db.session.delete(post)
    db.session.commit()
    flash('Your post has been deleted.')
    return redirect(url_for('.list_post'))


class switch(object):
    def __init__(self, value):
        self.value = value
        self.fall = False

    def __iter__(self):
        """Return the match method once, then stop"""
        yield self.match
        raise StopIteration

    def match(self, *args):
        """Indicate whether or not to enter a case suite"""
        if self.fall or not args:
            return True
        elif self.value in args:  # changed for v1.5, see below
            self.fall = True
            return True
        else:
            return False
