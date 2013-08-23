/* Schema Table and Column are just model classes that don't do much */
function Schema(name){
    this.name = name
    this.tables = []
}

function Table(name, schema){
    this.schema = schema;
    this.name = name;
    this.columns = [];
}

Table.prototype.fullName = function(){
    return this.schema.name + "." + this.name;
}

function Column(name, is_pk, table){
    this.name = name;
    this.table = table;
    this.is_pk = is_pk;
}

/*
 * Take in an object where the key is a schema name, and the value is an object
 * of tables, where the key is a table name, and the value is a list of
 * columns, where each item in the list is an object with a name and pk
 * attribute. Parse that into a list of Schema, Table and Column model objects
 */
function parseSchemata(schemata){
    var schemas = [];
    for(var schema_name in schemata){
        var schema = new Schema(schema_name);
        var tables = schemata[schema_name];
        for(var table_name in tables){
            var table = new Table(table_name, schema);
            var cols = tables[table_name];
            for(var i = 0; i < cols.length; i++){
                var col = cols[i];
                table.columns.push(new Column(col.name, col.pk, table));
            }
            schema.tables.push(table);
        }
        schemas.push(schema);
    }
    return schemas;
}

/*
 * Allows objects to register callbacks for events, and lets objects broadcast
 * events to all registered listeners.
 * Public methods:
 *     listenFor(string event_type_name, function callback)
 *     broadcast(obj this_argument for callback function, string event_type_name, obj argument to pass to callback)
 */
var EventRegistry = {
    listeners: {},
    listenFor: function(event_types, callback){
        // take a string like "click dblclick mouseover" and break it up
        var types = event_types.split(" ");
        // for each event, add it 
        for(var i = 0; i < types.length; i++){
            var type = types[i]; 
            if(!(type in this.listeners)){
                this.listeners[type] = [];
            }
            this.listeners[type].push(callback);
        }
    },
    // broadcast an event to all registered callback functions, using this_arg
    // as the this argument, for all listeners of event_type, passing along the
    // event_arg to the callback function
    broadcast: function(this_arg, event_type, event_arg){
        var listeners = this.listeners[event_type];
        for(var i = 0; i < listeners.length; i++){
            listeners[i].call(this_arg, event_arg);
        }
    }
}

/* 
 * Generates a unique key for any view object, and allows the view to be
 * retrieved using that key.
 * Public methods: 
 *     register(View object)
 *     getViewByKey(string key)
 */
var ViewRegistry = {
    key: 0,
    registry: {},
    register: function(view){
        this.key++;
        this.registry[this.key] = view;
        return this.key;
    },
    getViewByKey: function(key){
        return this.registry[key];
    }
}

/*
 * This view allows a user to pick out the fields, sorting options, and
 * criteria for the query.
 * Public methods:
 *     this(jquery dom element: container) -- inits the view
 *     renderTotals() -- shows or hides the "Total" row on the view
 *     toggleTotals() -- toggles the state of the "Total" row on the view
 *     toSQL(any object)() -- converts the current state of the view into fragments of a SQL statement
 *     render() -- Renders the view on the page
 *     appendColumn(ColumnView) -- Adds a column to the view
 */
function QueryColumnsView(container){
    this.element = null;
    this.container = container;
    this.is_totals_visible = false;
}

QueryColumnsView.prototype.renderTotals = function(){
    if(this.is_totals_visible){
        this.element.find(".totals").show();
    } else {
        this.element.find(".totals").hide();
    }
}

QueryColumnsView.prototype.toggleTotals = function(){
    this.is_totals_visible ^= true;
    this.renderTotals();
}

QueryColumnsView.prototype.toSQL = function(sql){
    sql = sql || {}
    var cols = this.element.find('.qc-col-inner');
    var cols_info = []
    for(var i = 0; i < cols.length; i++){
        var name = $(cols[i]).find('.qc-name').val();
        var total = $(cols[i]).find('.qc-total').val();
        var sort = $(cols[i]).find('.qc-sort').val();
        var show = $(cols[i]).find('.qc-show').prop("checked")
        var criteria = [];
        $(cols[i]).find('.qc-criteria').each(function(i, el){
            var val = $(this).val();
            if($.trim(val)){
                criteria.push(val);
            }
        });
        cols_info.push({
            name: name,
            total: (this.is_totals_visible) ? total : null,
            sort: sort || null,
            show: show,
            criteria: criteria
        })
    }

    sql.select = [];
    sql.order_by = [];
    sql.where = [];
    sql.group_by = [];
    for(var i = 0; i < cols_info.length; i++){
        var col_info = cols_info[i];
        var name = col_info.name;
        if(col_info.total && col_info.total != "group by"){
            name = col_info.total + "(" + col_info.name + ")";
        }
        if(col_info.show){
            sql.select.push(name);
        }
        if(col_info.sort){
            sql.order_by.push(col_info.name + " " + col_info.sort)
        }
        if(col_info.total == "group by"){
            sql.group_by.push(name)
        }

        if(col_info.criteria.length){
            var where = []
            for(var j = 0; j < col_info.criteria.length; j++){
                var val = col_info.criteria[j];
                where.push(name + " = " + val)
            }
            sql.where.push(where.join(" OR "))
        }
    }

    return sql;
}

QueryColumnsView.prototype.render = function(){
    var html = [];
    html.push(
        '<div class="query-columns-view">'
            + '<div class="inner">'
                + '<div class="qc-row">'
                    + '<div class="qc-col">'
                        + '<label class="handle">&nbsp;</label>'
                        + '<label>Field:</label>'
                        + '<label class="totals">Total:</label>'
                        + '<label>Sort:</label>'
                        + '<label>Show:</label>'
                        + '<label>Criteria:</label>'
                        + '<label>Or:</label>'
                        + '<label>&nbsp;</label>'
                        + '<label>&nbsp;</label>' 
                        + '<label>&nbsp;</label>' 
                        + '<label>&nbsp;</label>'
                        + '<label>&nbsp;</label>'
                    + '</div>'
                + '</div>'
            + '</div>'
        + '</div>'
    );
    this.element = $(html.join(""));
    this.container.append(this.element);
    this.element.on('click', '.icon-remove', function(){
        $(this).closest('.qc-col').remove();
    });
}

QueryColumnsView.prototype.appendColumn = function(column_view){
    var name = column_view.column.table.fullName() + "." + column_view.column.name;
    var html = [];
    html.push(
        "<div class='qc-col'>" 
            + "<label class='handle'>&nbsp;</label>"
            + "<div class='qc-col-inner'>"
                + "<label><input type='text' value='" + name + "' class='qc-name' /></label>"
                + "<label class='totals'><select name='' class='qc-total'>"
                    + "<option value='group by'>Group By</option>"
                    + "<option value='count'>Count</option>"
                    + "<option value='avg'>Average</option>"
                    + "<option value='max'>Max</option>"
                    + "<option value='min'>Min</option>"
                    + "<option value='stddev'>Std. Dev</option>"
                    + "<option value='sum'>Sum</option>"
                + "</select></label>"
                + "<label><select name='' class='qc-sort'>"
                    + "<option value=''></option>"
                    + "<option value='asc'>Ascending</option>"
                    + "<option value='desc'>Descending</option>"
                + "</select></label>"
                + "<label><input type='checkbox' class='qc-show' checked /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label><input type='text' class='qc-criteria' /></label>"
                + "<label style='text-align:center'><i class='icon-remove'></i></label>"
            + "</div>"
        + "</div>")
    this.element.find(".qc-row").append(html.join(""))

    this.element.find(".qc-row").sortable({
        axis: 'x',
        handle: '.handle',
        items: '.qc-col:not(:first)'
    });

    this.renderTotals();
}

/* The following is used to perform topological sort */
function Node(payload){
    this.edges = []
    this.payload = payload;
}

function topologicalSort(nodes){
    var WHITE = 0
    var GRAY = 1
    var BLACK = 2

    var visit = function(node, linked){
        node.color = GRAY
        for(var i = 0; i < node.edges.length; i++){
            if(node.edges[i].color == WHITE){
                visit(node.edges[i], linked)
            }
        }
        node.color = BLACK;
        linked.push(node)
    }

    var linked = []
    for(var i = 0; i < nodes.length; i++){
        nodes[i].color = WHITE;
    }

    for(var i = 0; i < nodes.length; i++){
        var node = nodes[i];
        if(node.color == WHITE){
            visit(node, linked);
        }
    }

    linked.reverse();
    return linked;
}

/*
 * Adds, removes and draws the relationships between ColumnViews. 
 * Public methods:
 *     render() -- render the view
 *     addRelationship(ColumnView a, ColumnView b, type="INNER" | "LEFT" | "RIGHT")
 *     removeRelationshipsRelatedToColumnView(ColumnView)
 *     redrawRelationshipsRelatedTo(TableView)
 *     toSQL(sql) -- Build a from clause based on the relationships, and add it to the SQL object as the `from` property
 */
function RelationshipView(container){
    this.relationships = [];
    this.container = container;
}

RelationshipView.prototype.toSQL = function(sql){
    sql = sql || {}
    // get a list of tables to be joined together
    var tables = [];
    // don't be hating on on O(n*m) algorithm
    for(var i = 0; i < this.relationships.length; i++){
        var rel = this.relationships[i];
        var t1 = rel.a.table_view;
        var t2 = rel.b.table_view;
        if(tables.indexOf(t1) == -1){
            tables.push(t1);
        }
        if(tables.indexOf(t2) == -1){
            tables.push(t2);
        }
    }

    // build a list of nodes, where each table is a node, and a relationship is an edge
    var nodes = {}
    for(var i = 0; i < tables.length; i++){
        var node = new Node(tables[i]);
        nodes[node.payload.key] = node;
    }
    // build a list of edges based on all the relationships
    for(var i = 0; i < this.relationships.length; i++){
        var rel = this.relationships[i];
        var a_node = nodes[rel.a.table_view.key];
        var b_node = nodes[rel.b.table_view.key];
        if(a_node.edges.indexOf(b_node) == -1){
            a_node.edges.push(b_node)
        }
    }
    var node_list = [];
    for(var i = 0; i < tables.length; i++){
        node_list.push(nodes[tables[i].key]);
    }
    node_list = topologicalSort(node_list); 
    tables = []
    for(var i = 0; i < node_list.length; i++){
        tables.push(node_list[i].payload);
    }

    var included_tables = {}
    included_tables[tables[0].key] = true;

    // add the first table to the list of included tables, clone the list of
    // relationships (so we can modify the list)
    sql.from = tables[0].table.name + " ";

    var relationships = this.relationships.slice(0); 
    // order the relationships by the position of the table in the list
    var table_order = {};
    for(var i = 0; i < tables.length; i++){
        table_order[tables[i].key] = i;
    }
    relationships.sort(function(rel_a, rel_b){
        var a_index = Math.max(table_order[rel_a.a.table_view.key], table_order[rel_a.b.table_view.key]);
        var b_index = Math.max(table_order[rel_b.a.table_view.key], table_order[rel_b.b.table_view.key]);
        return a_index - b_index;
    });

    for(var i = 1; i < tables.length; i++){
        // add this table to our list of included tables
        included_tables[tables[i].key] = true;
        var is_first_join = true;
        var join_conditions = []
        // find all the relationships that can be added with these tables. Loop
        // in reverse, since we delete elements from the list
        for(var j = relationships.length-1; j >= 0; j--){
            var rel = relationships[j]; 
            // can this relationship be formed by the included tables?
            if(!(rel.a.table_view.key in included_tables && rel.b.table_view.key in included_tables))
                continue

            // add in the join (making sure we only do this once)
            if(is_first_join){
                is_first_join = false;
                sql.from += rel.type + " JOIN " + tables[i].table.name + " ON ";
            }
            
            // add this relationship to the join condition for this table,
            // and then remove it
            join_conditions.push(rel.a.column.name + " = " + rel.b.column.name);
            relationships.splice(j, 1);
        }
        // form the on clause
        sql.from += join_conditions.join(" AND ") + " ";
    }
    return sql;
}

RelationshipView.prototype.render = function(){
    this.bindEvents();
}

RelationshipView.prototype.addRelationship = function(a, b, type){
    if(a.table_view.key > b.table_view.key){
        var tmp = a;
        a = b;
        b = tmp;
    }
    var relationship = {
        a: a,
        b: b,
        line: null,
        canvas: null,
        type: type || "INNER"
    }
    this.relationships.push(relationship);
    this.drawConnection(relationship, this.relationships.length - 1);
}

RelationshipView.prototype.removeRelationshipsRelatedToColumnView = function(column_view){
    for(var i = this.relationships.length - 1; i >= 0; i--){
        if(this.relationships[i].a == column_view || this.relationships[i].b == column_view){
            this.removeRelationshipByIndex(i);
        }
    }
}

RelationshipView.prototype.redrawRelationshipsRelatedTo = function(table_view){
    // index all the column_views in the table_view by their ViewRegistry key
    var keys = {};
    for(var i = 0; i < table_view.column_views.length; i++){
        keys[table_view.column_views[i].key] = true;
    }

    // find all the relationships where one end of the relationship is in `keys`
    for(var i = 0; i < this.relationships.length; i++){
        var relationship = this.relationships[i];
        if(relationship.a.key in keys || relationship.b.key in keys){
            this.drawConnection(relationship, i);
        }
    }
}

RelationshipView.prototype.removeRelationshipByIndex = function(index){
    var removed = this.relationships.splice(index, 1);
    removed[0].canvas.remove();
}

// This handles drawing a line between a relationship. It's complex.
RelationshipView.prototype.drawConnection = function(relationship){
    var a = relationship.a;
    var b = relationship.b;
    var b_offset = b.element.find(".column-dragger").offset();
    var a_offset = a.element.find(".column-dragger").offset();
    var a_width = a.element.closest(".table-view").width();
    var b_width = b.element.closest(".table-view").width();

    // we need to bump the line down just a bit so that it is aligned with the
    // middle of the column name text
    var vertical_offset = 10;
    var horizontal_offset = 20;
    /*      +--+---------------- this distance is the horizontal_offset of the line
     * +---+|  |    
     * |   |----\   
     * | A |     \  
     * |   |      \     +---+
     * +---+       \----|   |
     *                  | B |
     *                  |   |
     *                  +---+
     */

    // based on the type of join, AND the order of the tables, the join arrow
    // point "LEFT" or "RIGHT" (or be the empty string in the case of INNER joins
    var join_arrow = "";
    if((a_offset.left + (a_width/2)) < (b_offset.left + (b_width/2))){
        // the line connecting columns `a` and `b` should start at the right
        // side of `a`, and go to the left of `b`
        var start_x = a_offset.left+a_width;
        var start_y = a_offset.top + vertical_offset;

        var end_x = b_offset.left;
        var end_y = b_offset.top + vertical_offset

        if(relationship.type == "LEFT"){
            join_arrow = "RIGHT";
        } else if(relationship.type == "RIGHT") {
            join_arrow = "LEFT";
        } 
    } else {
        // the line connecting columns `a` and `b` should start at the left
        // side of `a`, and go to the right of `b`
        var start_x = a_offset.left;
        var start_y = a_offset.top + vertical_offset;

        var end_x = b_offset.left + b_width;
        var end_y = b_offset.top + vertical_offset;

        if(relationship.type == "LEFT"){
            join_arrow = "LEFT";
        } else if(relationship.type == "RIGHT") {
            join_arrow = "RIGHT";
        } 
    }

    var top = Math.min(start_y, end_y);
    var left = Math.min(start_x, end_x);
    var width = Math.abs(start_x - end_x);
    var height = Math.abs(start_y - end_y);

    // this relationship hasn't been drawn before, so we need to initialize the
    // canvas and line
    if(relationship.canvas == null){
        relationship.canvas = $('<svg xmlns="http://www.w3.org/2000/svg" pointer-events="none" version="1.1" style="background:none; position:absolute; top:0; left:0; "> </svg>');
        relationship.line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        relationship.canvas.get()[0].appendChild(relationship.line);
        relationship.line.setAttribute("class", "relationship");
        relationship.line.setAttribute("pointer-events", "stroke");
        this.container.append(relationship.canvas);
        this.bindLineEvents(relationship.line);

        // add the line elements for the arrows
        relationship.arrow = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        relationship.canvas.get()[0].appendChild(relationship.arrow);
        relationship.arrow.setAttribute("class", "relationship-arrow");
    }

    // because of the stroke of the line, and the arrow, we need to pad the
    // canvas a little bit all around
    var padding = 30;
    relationship.canvas.css({
        top: top-padding,
        left: left-padding,
        width: width + padding*2,
        height: height + padding*2
    });

    // there are four types of lines that can be drawn to form the connection
    // between the two columns
    var z_shape = (a_offset.left + a_width < b_offset.left) && (a_offset.top < b_offset.top)
                  ||
                  (b_offset.left + b_width < a_offset.left) && (b_offset.top < a_offset.top)

    var s_shape = (a_offset.left + a_width < b_offset.left) && (a_offset.top >= b_offset.top)
                  ||
                  (b_offset.left + b_width < a_offset.left) && (b_offset.top >= a_offset.top)

    var z_shape_inner = (a_offset.left + a_width/2 < b_offset.left+b_width/2) && (a_offset.top < b_offset.top)
                        ||
                        (b_offset.left + b_width/2 < a_offset.left+a_width/2) && (b_offset.top < a_offset.top)

    // s_shape_inner (this is the only other case so we don't need to calculate it)

    // define the path for the correct type of line
    if(z_shape){
        var path = "M " + padding + " " + padding + " l " + horizontal_offset + " 0 l " + (width-horizontal_offset*2) + " " + (height) + " l " + horizontal_offset + " 0 ";
    } else if(s_shape){
        var path = "M " + padding + " " + (padding+height) + " l " + horizontal_offset + " 0 l " + (width-horizontal_offset*2) + " " + (-height) + " l " + horizontal_offset + " 0 ";
    } else if(z_shape_inner) {
        var path = "M " + (width+padding) + " " + padding + " l " + horizontal_offset + " 0 L " + (padding-horizontal_offset) + " " + (height+padding) + " l " + horizontal_offset + " 0 ";
    } else { // s_shape_inner
        var path = "M " + (padding) + " " + padding + " l " + (-horizontal_offset) + " 0 " + " L " + (width+padding+horizontal_offset) + " " + (height+padding) + " l " + (-horizontal_offset) + " 0 ";
    }

    relationship.line.setAttribute("d", path);

    // now form the arrow on the line if applicable. This code just defines the
    // starting point of the arrow
    var path = "";
    if(z_shape){
        if(join_arrow == "LEFT"){
            var path = "M " + padding + " " + padding + " ";
        } else if(join_arrow == "RIGHT"){
            var path = "M " + (padding+width) + " " + (height+padding)
        }
    } else if(z_shape_inner){
        if(join_arrow == "LEFT"){
            var path = "M " + (padding+width) + " " + padding
        } else if(join_arrow == "RIGHT"){
            var path = "M " + (padding) + " " + (height+padding);
        }
    } else if(s_shape){
        if(join_arrow == "LEFT"){
            var path = "M " + padding + " " + (height+padding);
        } else if(join_arrow == "RIGHT"){
            var path = "M " + (width+padding) + " " + padding;
        }
    } else { // s_shape_inner
        if(join_arrow == "LEFT"){
            var path = "M " + (padding + width) + " " + (height+padding)
        } else if(join_arrow == "RIGHT"){
            var path = "M " + (padding) + " " + padding;
        }
    }

    // this appends the path of the arrow to the starting position
    if(join_arrow == "LEFT"){ 
        path += " l 10 10 m -10 -10 l 10 -10 ";
    } else if(join_arrow == "RIGHT"){
        path += " l -10 -10 m 10 10 l -10 10 ";
    } else {
        // in the case of INNER joins, move the arrow out of the viewable area
        path = "M -100 -100";
    }

    relationship.arrow.setAttribute("d", path);
}

RelationshipView.prototype.setActiveRelationship = function(line_element){
    // find the active line element, and reset the class back to just "relationship"
    var active = this.container.find(".relationship.active").get()
    if(active.length > 0){ 
        active[0].setAttribute("class", "relationship");
    }

    if(line_element){
        // add the active class to the line element
        line_element.setAttribute("class", "relationship active");
    }
}

RelationshipView.prototype.bindLineEvents = function(line){
    var that = this;
    line = $(line);
    // this prevents text from being highlighted on the dblclick 
    // (http://stackoverflow.com/questions/880512/prevent-text-selection-after-double-click)
    line.on('mousedown', function(e){ e.preventDefault() });

    // when a relationship is clicked set it as the active one
    line.on('click', function(e){ 
        that.setActiveRelationship(this);
        // prevent the body.click event from firing (since that will deactivate
        // the active line)
        e.stopPropagation();
    });

    line.on('dblclick', function(e){
        // find the relationship that was clicked
        var index = that.getIndexOfLine(this);
        var relationship = that.relationships[index];
        // when the relationship is dblclicked, inform the event registry 
        EventRegistry.broadcast(that, "dblclick", {
            relationship: relationship
        });

        // toggle the direction of the join (which will require a redraw)
        var join = ["INNER", "LEFT", "RIGHT"];
        relationship.type = join[(join.indexOf(relationship.type)+1) % join.length];
        that.drawConnection(relationship);
    });
}

RelationshipView.prototype.getIndexOfLine = function(line){
    // given a dom line element, find the relationship that it belongs to
    for(var i = 0; i < this.relationships.length; i++){
        if(this.relationships[i].line == line) return i;
    }
    return -1;
}

RelationshipView.prototype.bindEvents = function(relationship){
    var that = this;
    // bind to the body element and watch for
    // DEL key presses. When the DEL key is pressed, and we have an active
    // relationship (i.e. the user clicked on a line), we delete the relationship
    var keys_to_watch = [46];
    $('body').bind("keydown", function(e){
        if(keys_to_watch.indexOf(e.keyCode) == -1) return; // only watch for defined keys
        e.preventDefault();
        var active_element = that.container.find(".relationship.active");
        if(active_element.length != 1) return;
        var index = that.getIndexOfLine(active_element.get(0));

        if(e.keyCode == 46){
            // delete the active relationship (if there is one)
            // find the active element
            that.removeRelationshipByIndex(index);
        }
    });

    // when something is clicked, set the active relationship to nothing
    $('body').bind("click", function(e){
        that.setActiveRelationship(null);
    });
}

/* This is a row in a TableView that represents a column in the TableView 
 * Public methods:
 *     this(Column, some_dom element to append this column view to, TableView)
 *     render() -- draw the ColumnView
 */
function ColumnView(column, container, table_view){
    this.column = column;
    this.container = container;
    this.element = null;
    this.key = ViewRegistry.register(this);
    this.table_view = table_view;
}

ColumnView.prototype.render = function(){
    var cls = ""
    if(this.column.is_pk) cls = 'primary-key';
    this.element = $(
        '<tr class="column-view">'
            + '<td>'
                + '<i class="icon-resize-horizontal column-dragger table-view-' + this.table_view.key + '" data-key="' + this.key + '"></i>'
            + '</td>'
            + '<td class="name">' + this.column.name + '</td>'
        + '</tr>');
    this.container.append(this.element);
    this.bindEvents(); 

    // reset the draggable and droppable behaviors
    try {
        $('.column-dragger').draggable("destroy");
        $('.column-dragger').droppable("destroy");
    } catch(e){ }

    // make all the column draggers draggable
    $('.column-dragger').draggable({
        appendTo: 'body',
        helper: 'clone',
        zIndex: 3
    });

    // make all the column draggers droppable too
    $('.column-dragger').droppable({
        hoverClass: 'droppable',
        accept: function(droppable){
            // make sure you can't form a relationship between columns in the
            // same table by making sure the table-view-(some-number) class on
            // the elements don't match
            var table_view_class_a = $(droppable).attr("class").match(/table-view-\d+/)
            var table_view_class_b = $(this).attr("class").match(/table-view-\d+/)
            if(table_view_class_a == null || table_view_class_b == null) return false;
            return table_view_class_a[0] != table_view_class_b[0];
        },
        drop: function(event, ui){
            var from = $(event.srcElement);
            var to = $(this);

            var from_key = from.data("key");
            var to_key = to.data("key");

            var from_view = ViewRegistry.getViewByKey(from_key);
            var to_view = ViewRegistry.getViewByKey(to_key);

            EventRegistry.broadcast(this, "relationship_formed", {
                a: to_view,
                b: from_view
            })
        }
    });
}

ColumnView.prototype.bindEvents = function(){
    var that = this;
    this.element.find('.name').on('click', function(e){
        EventRegistry.broadcast(that, 'click', {
        });
    });
}

function TableView(table, container){
    this.table = table;
    this.container = container;
    this.element = null;
    this.column_views = [];
    this.key = ViewRegistry.register(this);
}

TableView.prototype.render = function(){
    var html = [
        '<div class="table-view">'
            + '<div class="header">'
                + '<span class="remove"><i class="icon-remove"></i></span> ' + this.table.fullName() 
            + '</div>'
            + '<input type="text" name="table-name" value="' + this.table.name + '" />'
            + '<table class="columns"><tbody></tbody></table>'
        + '</div>'];
    this.element = $(html.join(""));
    this.container.append(this.element);

    var column_div = this.element.find(".columns");
    this.column_views = [];
    for(var i = 0; i < this.table.columns.length; i++){
        var cv = new ColumnView(this.table.columns[i], column_div, this)
        cv.render();
        this.column_views.push(cv);
    }

    var that = this;
    // make myself draggable
    $(this.element).draggable({
        'handle': '.header',
        'drag': function(){ EventRegistry.broadcast(that, "drag", null) },
        'stop': function() { EventRegistry.broadcast(that, "stop", null) }
    });

    this.bindEvents();
}

TableView.prototype.remove = function(){
    EventRegistry.broadcast(this, "closed", null);
    this.element.remove();
}

TableView.prototype.bindEvents = function(){
    var that = this;
    $(this.element).find('.icon-remove').on('click', function(){
        that.remove();
    });
}

function SchemataView(schemas, container){
    this.container = container;
    this.schemas = schemas;
}

SchemataView.prototype.render = function(){
    var html = ['<ul>'];
    for(var i = 0; i < this.schemas.length; i++){
        var schema = this.schemas[i];
        html.push(
            "<li class='schema-info'>"
                + "<span class='schema-name'>"
                    + "<i class='icon-folder-close'></i> " + schema.name 
                + "</span>"
                + "<ul class='table-list'>");
        var tables = schema.tables;
        for(var j = 0; j < tables.length; j++){
            html.push(
                "<li>"
                    + "<i class='icon-list-alt'></i> "
                    + "<span class='table-name'>" + tables[j].name + "</span>"
                + "</li>")
        }
        html.push("</ul></li>");
    }

    this.container.find('.schemata-list').html(html.join(""))
    this.collapseAllTableLists();
    this.bindEvents();
}

SchemataView.prototype.collapseAllTableLists = function(){
    this.container.find(".table-list").hide();
}

SchemataView.prototype.tableObjectFromDOM = function(element){
    var table_name = $.trim($(element).text());
    var schema_name = $.trim($(element).closest('.schema-info').find('.schema-name').text());
    var table = this.findTableObject(schema_name, table_name);
    return table;
}

SchemataView.prototype.findTableObject = function(schema_name, table_name){
    // find the schema object
    for(var i = 0; i < this.schemas.length; i++){
        var schema = this.schemas[i];
        if(schema.name == schema_name) break;
    }

    // now find the table object
    for(var i = 0; i < schema.tables.length; i++){
        var table = schema.tables[i];
        if(table.name == table_name) return table;
    }

    return null;
}

SchemataView.prototype.bindEvents = function(){
    // when the schema name is clicked, slide up or down the list of tables,
    // and change the folder icon to either open or closed
    this.container.find(".schema-name").on('click', function(){
        var table_list = $(this).closest("li").find('.table-list');
        var icon = $(this).find("i");
        if(table_list.is(":visible")){
            table_list.slideUp();
            icon.removeClass("icon-folder-open").addClass("icon-folder-close");
        } else {
            table_list.slideDown();
            icon.addClass("icon-folder-open").removeClass("icon-folder-close");
        }
    });

    // notify the event listeners
    var that = this;
    this.container.on('click', '.table-name', function(){
        var table = that.tableObjectFromDOM($(this));
        var event = {
            table: table,
        }
        EventRegistry.broadcast(that, "click", event);
    });
}
