# -*- coding: utf-8 -*-
"""
    Group Photo Sharing
    ~~~~~~~~~~~~~~~~~~~

    A Photo sharing application that creates a image montage employing 
    the 2 phase commit protocol
"""

import os
import glob
import shelve
import shutil
import time
import requests
import json
from PIL import Image
from StringIO import StringIO
from sqlite3 import dbapi2 as sqlite3
from flask import Flask, request, session, g, redirect, url_for, abort, \
     render_template, flash, send_from_directory, make_response, jsonify, \
     send_file
from werkzeug.utils import secure_filename
from threading import Timer

UPLOAD_FOLDER = os.path.realpath('.') + '/images/'
MONTAGE_FOLDER = os.path.realpath('.') + '/montages/'
CURMONTAGE_FOLDER = os.path.realpath('.') + '/curmontage/'
MONTAGE_FILE = 'tmpmontage.jpg'
INTENTIONS_DB = 'intentions.db'
SERVER_LIST = [7000, 7001, 7002]
my_port = 7002
master_port = 7000

# create our little application :)
app = Flask(__name__)

# Load default config and override config from an environment variable
app.config.update(dict(
    DATABASE=os.path.join(app.root_path, 'groupphotosharing.db'),
    DEBUG=True,
    SECRET_KEY='development key'
))
app.config.from_envvar('GROUPPHOTOSHARING_SETTINGS', silent=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MONTAGE_FOLDER'] = MONTAGE_FOLDER
app.config['CURMONTAGE_FOLDER'] = CURMONTAGE_FOLDER

def make_montage(fnames,(ncols,nrows),(photow,photoh),
                       (marl,mart,marr,marb),
                       padding):
    """\
    Make a contact sheet from a group of filenames:

    fnames       A list of names of the image files
    
    ncols        Number of columns in the contact sheet
    nrows        Number of rows in the contact sheet
    photow       The width of the photo thumbs in pixels
    photoh       The height of the photo thumbs in pixels

    marl         The left margin in pixels
    mart         The top margin in pixels
    marr         The right margin in pixels
    marb         The bottom margin in pixels

    padding      The padding between images in pixels

    returns a PIL image object.
    """

    # Calculate the size of the output image, based on the
    #  photo thumb sizes, margins, and padding
    marw = marl+marr
    marh = mart+ marb

    padw = (ncols-1)*padding
    padh = (nrows-1)*padding
    isize = (ncols*photow+marw+padw,nrows*photoh+marh+padh)

    # Create the new image. The background doesn't have to be white
    white = (255,255,255)
    inew = Image.new('RGB',isize,white)

    count = 0
    # Insert each thumb:
    for irow in range(nrows):
        for icol in range(ncols):
            left = marl + icol*(photow+padding)
            right = left + photow
            upper = mart + irow*(photoh+padding)
            lower = upper + photoh
            bbox = (left,upper,right,lower)
            try:
                # Read in an image and resize appropriately
                img = Image.open(fnames[count]).resize((photow,photoh))
            except:
                break
            inew.paste(img,bbox)
            count += 1
    return inew

def get_intentions_store():
    """Opens the intentions list from the server filesystem
    """
    intentions_db = shelve.open(os.path.join(app.root_path, INTENTIONS_DB))
    return intentions_db

@app.teardown_appcontext
def close_db(error):
    """Closes the database again at the end of the request."""
    if hasattr(g, 'intentions_db'):
        g.intentions_db.close()

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/montages/<filename>')
def montage_file(filename):
    return send_from_directory(app.config['MONTAGE_FOLDER'], filename)

@app.route('/curmontage/<filename>')
def curmontage_file(filename):
    return send_from_directory(app.config['CURMONTAGE_FOLDER'], filename)

@app.route('/')
def show_entries():
    if not hasattr(g, 'up_to_date'):
        g.up_to_date = False

    if not g.up_to_date and not my_port == master_port:
        url_get_image = 'http://localhost:'+str(master_port)+'/get_image'
        url_list_image = 'http://localhost:'+str(master_port)+'/list_image'
        r = requests.get(url_list_image)
        resp_json = r.json()
        for filename in resp_json['file_list']:
            payload = { 'filename': filename }
            r = requests.get(url_get_image, params=payload)
            img = Image.open(StringIO(r.content))
            img.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        g.up_to_date = True

    if 'username' in request.cookies:
        session['logged_in'] = True
        session['username'] = request.cookies.get('username')
    else:
        return redirect(url_for('login'))

    intentions = get_intentions_store()
    if session.get('logged_in'):
        if intentions.has_key('cannot_upload'.encode('ascii','ignore')):
            session['cannot_upload'] = intentions['cannot_upload']
        if intentions.has_key(session.get('username').encode('ascii','ignore')):
            session['cannot_vote'] = intentions[session.get('username').encode('ascii','ignore')]
    else:
            session['cannot_upload'] = False
            session['cannot_vote'] = False

    current_montage_available=False
    ncols,nrows = 3,4
    files = glob.glob(os.path.realpath('.')+'\images\*.*')
    # Don't bother reading in files we aren't going to use
    if len(files) > ncols*nrows: 
        files = files[:ncols*nrows]
    # These are all in terms of pixels:
    photow,photoh = 133,150
    photo = (photow,photoh)
    margins = [5,5,5,5]
    padding = 1
    if files:
        inew = make_montage(files,(ncols,nrows),photo,margins,padding)
        inew.save(os.path.join(app.config['CURMONTAGE_FOLDER'], MONTAGE_FILE))
        current_montage_available=True
    publishedfiles = os.listdir('./montages')
    return render_template('show_entries.html', publishedmontages=publishedfiles, 
        montage_state=current_montage_available)

@app.route('/add', methods=['POST'])
def add_entry():
    global my_port
    intentions = get_intentions_store()
    if not session.get('logged_in'):
        abort(401)

    can_add = True
    if intentions.has_key('cannot_upload'.encode('ascii','ignore')):
        can_add = not intentions['cannot_upload']

    if request.method == 'POST' and 'photo' in request.files and can_add:
        file = request.files['photo']
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        for port in SERVER_LIST:
            if not port == my_port:
                try:
                    send_image(os.path.join(app.config['UPLOAD_FOLDER'], filename), port)
                except requests.exceptions.RequestException:
                    continue
        flash('Photo Saved')
    else:
        if not can_add:
            flash('Voting has begun. You cannot upload till voting is done')
        else:
            flash('No photo found in request')

    return redirect(url_for('show_entries'))

@app.route('/vote', methods=['POST'])
def vote():
    intentions = get_intentions_store()
    if not session.get('logged_in'):
        abort(401)
    if session.get('cannot_vote'):
        flash('You have already voted. You cannot change your vote')
        return redirect(url_for('show_entries'))
    if request.method == 'POST':
        if intentions.has_key('cannot_upload'.encode('ascii','ignore')):
            if not intentions['cannot_upload'.encode('ascii','ignore')]:
                intentions['cannot_upload'.encode('ascii','ignore')] = True
                intentions.sync()
                Timer(60, check_and_commit, ()).start()
            else:
                intentions['cannot_upload'.encode('ascii','ignore')] = True
                intentions.sync()
        else:
            intentions['cannot_upload'.encode('ascii','ignore')] = True
            intentions.sync()
            Timer(60, check_and_commit, ()).start()

        vote_val = request.form['vote_val']
        if vote_val == 'Yes':
            flash('You voted yes')
            intentions[session.get('username').encode('ascii','ignore')] = True
            intentions.sync()
            session['cannot_upload'] = True
            session['cannot_vote'] = True
        elif vote_val == 'No':
            flash('You voted no')
            intentions[session.get('username').encode('ascii','ignore')] = False
            intentions.sync()
            session['cannot_upload'] = True
            session['cannot_vote'] = True
    redirect_to_index = redirect(url_for('show_entries'))
    response = app.make_response(redirect_to_index)
    return response

@app.route('/check_and_commit', methods=['GET', 'POST'])
def check_and_commit():
    intentions = get_intentions_store()
    can_commit = True
    users = []

    if not os.path.isfile(os.path.join(app.config['CURMONTAGE_FOLDER'], MONTAGE_FILE)):
        return

    if intentions.has_key('user_list'):
        users = intentions['user_list']

    for user in users:
        if intentions.has_key(user.encode('ascii', 'ignore')):
            if not intentions[user.encode('ascii', 'ignore')]:
                can_commit = False
        else:
            can_commit = False

    if can_commit:
        if intentions.has_key('montage_version'.encode('ascii','ignore')):
            montage_version = intentions['montage_version']+1
        else:
            montage_version = 1

        intentions['montage_version'] = montage_version

        shutil.copy2(os.path.join(app.config['CURMONTAGE_FOLDER'], MONTAGE_FILE), 
            os.path.join('./montages/', str(montage_version)+'.jpg') )

        files1 = glob.glob(os.path.realpath('.')+'\images\*.*')
        for f in files1:
            os.remove(f)

        files2 = glob.glob(os.path.realpath('.')+'\curmontage\*.*')
        for f in files2:
            os.remove(f)

    for user in users:
        intentions[user.encode('ascii', 'ignore')] = False

    intentions['cannot_upload'] = False
    intentions.sync()


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    intentions = get_intentions_store()
    if request.method == 'POST':
        username = request.form['username'] 
        if intentions.has_key('user_list'):
            users = intentions['user_list']
            users.append(username)
            intentions['user_list'] = users
        else:
            users = []
            users.append(username)
            intentions['user_list'] = users
            
        flash('You were logged in')
        session['logged_in'] = True
        session['username'] = username
        redirect_to_index = redirect(url_for('show_entries'))
        response = app.make_response(redirect_to_index)
        response.set_cookie('username', username)
        return response
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    session.pop('cannot_upload', None)
    session.pop('cannot_vote', None)
    flash('You were logged out')
    redirect_to_index = redirect(url_for('show_entries'))
    response = app.make_response(redirect_to_index)
    response.set_cookie('username', expires=0)
    return response

@app.route('/post_image', methods=['POST'])
def post_image():
    file = request.files['file']
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    response = app.make_response('')
    response.status_code = 200
    return response

@app.route('/list_image', methods=['GET'])
def list_image():
    file_list = os.listdir(os.path.realpath('.')+'\images')
    return jsonify(file_list=file_list)

@app.route('/get_image', methods=['GET'])
def get_image():
    filename = request.args.get('filename')
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

def send_image(image, port):
    url = 'http://localhost:'+str(port)+'/post_image'
    files = {'file': open(image, 'rb')}
    r = requests.post(url, files=files)
    return r.status_code

def check_and_createdir(path):
    dir = os.path.dirname(path)
    if not os.path.exists(dir):
        os.makedirs(dir)

if __name__ == '__main__':
    check_and_createdir(app.config['UPLOAD_FOLDER'])
    check_and_createdir(app.config['MONTAGE_FOLDER'])
    check_and_createdir(app.config['CURMONTAGE_FOLDER'])
    check_and_commit()
    global my_port
    global master_port
    app.run(host='0.0.0.0', port=my_port)