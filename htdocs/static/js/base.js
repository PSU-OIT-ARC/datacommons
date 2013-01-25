$(document).ready(function(){
    // convert all timestamps to local time
    $('.timestamp').each(function(i){
        var ts = parseInt($(this).text(), 10);
        var d = new Date(ts * 1000);
        $(this).text(d.toLocaleString());
    });
});
